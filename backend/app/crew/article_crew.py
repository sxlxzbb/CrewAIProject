"""CrewAI 编排：技术媒体编辑部。

特性：
- 配置外置（agents.yaml / tasks.yaml）
- 结构化输出（Pydantic）
- LLM 调用重试（exponential backoff）
- CrewAI Flow 实现「写→审→改」回环（带最大回合数守卫）
- 可观测性接入（langfuse_client.trace_run 包裹）
"""
import time
import logging
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# 显式加载项目根目录 .env，确保 CrewAI / Langfuse SDK 能读到
# LANGFUSE_* 与 CREWAI_TRACING_ENABLED 等环境变量（它们直接读 os.environ）。
_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"
if _ROOT_ENV.exists():
    load_dotenv(_ROOT_ENV, override=True)
from pydantic import BaseModel, Field
from crewai import LLM, Agent, Task, Crew, Process
from crewai.flow.flow import Flow, listen, start
from crewai_tools import TavilySearchTool

from app.config.settings import settings
from app.observability.langfuse_client import trace_run

logger = logging.getLogger("crew")

# 配置目录：本文件所在 crew/ 的上一级的 config/
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


class ArticleOutput(BaseModel):
    """结构化产出：便于前端展示与下游消费。"""
    title: str = Field(description="文章标题")
    body: str = Field(description="文章正文")
    keywords: list[str] = Field(default_factory=list, description="关键词")


def _retry(max_attempts: int = 3, backoff: float = 2.0):
    """简单指数退避重试装饰器。"""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last = e
                    logger.warning(f"[retry] 第 {attempt} 次失败: {e}")
                    if attempt < max_attempts:
                        time.sleep(backoff ** attempt)
            logger.error(f"[retry] 已耗尽重试次数: {last}")
            raise last
        return wrapper
    return decorator


class TechMediaCrew:
    """简化版技术媒体编辑部（可落地封装）。"""

    def __init__(self):
        self._setup_llm()
        self._setup_tools()
        self._load_config()
        self._build_agents()

    def _setup_llm(self):
        self.llm = LLM(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            model=settings.model_name,
            temperature=settings.temperature,
        )

    def _setup_tools(self):
        self.search_tool = TavilySearchTool(max_results=3)

    def _load_config(self):
        self.agent_cfg = _load_yaml("agents.yaml")
        self.task_cfg = _load_yaml("tasks.yaml")

    def _build_agents(self):
        common = dict(llm=self.llm, verbose=True, max_iter=settings.max_iter)
        a = self.agent_cfg
        self.researcher = Agent(
            role=a["researcher"]["role"],
            goal=a["researcher"]["goal"],
            backstory=a["researcher"]["backstory"],
            tools=[self.search_tool],
            **common,
        )

        self.analyst = Agent(
            role=a["analyst"]["role"],
            goal=a["analyst"]["goal"],
            backstory=a["analyst"]["backstory"],
            **common,
        )

        self.writer = Agent(
            role=a["writer"]["role"],
            goal=a["writer"]["goal"],
            backstory=a["writer"]["backstory"],
            **common,
        )

        self.editor = Agent(
            role=a["editor"]["role"],
            goal=a["editor"]["goal"],
            backstory=a["editor"]["backstory"],
            **common,
        )

    @_retry()
    def _run_crew(self, topic: str) -> str:
        t = self.task_cfg
        research_task = Task(
            description=t["research_task"]["description"].format(topic=topic),
            agent=self.researcher,
            expected_output=t["research_task"]["expected_output"],
        )

        analysis_task = Task(
            description=t["analysis_task"]["description"].format(topic=topic),
            agent=self.analyst,
            expected_output=t["analysis_task"]["expected_output"],
            context=[research_task],
        )

        writing_task = Task(
            description=t["writing_task"]["description"].format(topic=topic),
            agent=self.writer,
            expected_output=t["writing_task"]["expected_output"],
            context=[research_task, analysis_task],
        )

        editing_task = Task(
            description=t["editing_task"]["description"],
            agent=self.editor,
            expected_output=t["editing_task"]["expected_output"],
            context=[writing_task],
        )

        crew = Crew(
            agents=[self.researcher, self.analyst, self.writer, self.editor],
            tasks=[research_task, analysis_task, writing_task, editing_task],
            verbose=True,
            process=Process.sequential,
            tracing=True,  # CrewAI 原生集成 Langfuse：配好 key 即自动上报
        )

        result = crew.kickoff()
        return str(result)

    def generate(self, topic: str, user: Optional[str] = None) -> str:
        """对外主入口：包裹可观测性与重试。"""
        with trace_run("tech_media_crew", topic=topic, user=user):
            return self._run_crew(topic)


# ---- CrewAI Flow：实现「写 → 审 → 改」回环 ----
MAX_REVISION_ROUNDS = 3


class EditorialFlow(Flow):
    """带审校回环的编辑流程。"""

    def __init__(self, crew: TechMediaCrew):
        super().__init__()
        self.crew = crew

    @start()
    def draft(self):
        self.state["topic"] = self.state.get("topic", "")
        # 首轮：直接走完整 Crew（含一次内审）
        self.state["draft"] = self.crew.generate(self.state["topic"], self.state.get("user"))

    @listen(draft)
    def review(self):
        # 简易质量门禁：若主编产出明显过短或有占位符，触发重写
        text = self.state.get("draft", "")
        if len(text) < 300 or "待补充" in text:
            self.state["needs_revision"] = True
        else:
            self.state["needs_revision"] = False

    @listen(review)
    def maybe_revise(self):
        rounds = self.state.get("rounds", 0)
        if self.state.get("needs_revision") and rounds < MAX_REVISION_ROUNDS:
            self.state["rounds"] = rounds + 1
            # 把主编的具体修改意见作为定向反馈，传给写作任务进行修订
            feedback = self.state.get("feedback", "")
            logger.info(f"[editorial_flow] 第 {rounds + 1} 轮重写，主编意见: {feedback[:200]}")
            self.state["draft"] = self.crew.generate(
                self.state["topic"], self.state.get("user"),
                revision_feedback=feedback,
            )
            return self.maybe_revise()
        return self.state.get("draft", "")


def run_flow(topic: str, user: Optional[str] = None) -> str:
    """便捷函数：运行带审校回环的编辑流程。"""
    crew = TechMediaCrew()
    flow = EditorialFlow(crew)
    flow.state["topic"] = topic
    flow.state["user"] = user
    flow.state["rounds"] = 0
    with trace_run("editorial_flow", topic=topic, user=user):
        return flow.kickoff()
