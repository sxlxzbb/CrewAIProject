"""CrewAI 编排：技术媒体编辑部。

特性：
- 配置外置（agents.yaml / tasks.yaml）
- 结构化输出（Pydantic）
- LLM 调用重试（exponential backoff）
- CrewAI Flow 实现「写→审→改」回环（带最大回合数守卫），
  Crew 内只负责「调研→分析→写作」，审校门禁由 Flow 的 review 阶段负责
- 可观测性：CrewAI 原生 tracing 上报至 CrewAI AMP（依赖 CREWAI_API_KEY），
  本地运行日志由 langfuse_client.trace_run 包裹记录。
"""
import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# 显式加载项目根目录 .env，确保 CrewAI SDK 能读到
# CREWAI_API_KEY 与 CREWAI_TRACING_ENABLED 等环境变量（它们直接读 os.environ）。
_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"
if _ROOT_ENV.exists():
    load_dotenv(_ROOT_ENV, override=True)

from pydantic import BaseModel, Field
from crewai import LLM, Agent, Task, Crew, Process
from crewai.flow.flow import Flow, listen, start
from crewai_tools import TavilySearchTool

from app.config.settings import settings
from app.observability.langfuse_client import trace_run
from app.util.logger import get_logger

logger = get_logger("crew")

# 配置目录：本文件所在 crew/ 的上一级的 config/
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


class ArticleOutput(BaseModel):
    """结构化产出：便于前端展示与下游入库。"""
    title: str = Field(description="文章标题")
    summary: str = Field(default="", description="文章摘要（100字以内）")
    body: str = Field(default="", description="文章正文")
    keywords: list[str] = Field(default_factory=list, description="关键词列表")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="置信度（0~1，表示内容可信/完整程度）"
    )


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
        self._setup_editor_llm()
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

    def _setup_editor_llm(self):
        """审校(主编)专用 LLM：若 .env 配置了 EDITOR_* 则使用，否则回退主模型。"""
        name = settings.editor_model_name or settings.model_name
        key = settings.editor_dashscope_api_key or settings.dashscope_api_key
        base_url = settings.editor_dashscope_base_url or settings.dashscope_base_url
        temp = settings.editor_temperature
        logger.info(f"审校Agent LLM配置,model_name:{name},key:{key},base_url:{base_url},temp:{temp}")
        self.editor_llm = LLM(
            api_key=key,
            base_url=base_url,
            model=name,
            temperature=temp,
        )

    def _setup_tools(self):
        self.search_tool = TavilySearchTool(max_results=3)

    def _load_config(self):
        self.agent_cfg = _load_yaml("agents.yaml")
        self.task_cfg = _load_yaml("tasks.yaml")

    def _build_agents(self):
        common = dict(llm=self.llm, verbose=True, max_iter=settings.max_iter)
        editor_common = dict(common, llm=self.editor_llm)
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
            **editor_common,
        )

    @_retry()
    def _run_crew(self, topic: str, revision_feedback: str = None) -> str:
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

        # 重写轮次：把「主编修改意见」作为定向反馈注入写作任务，使作者按意见改稿
        writing_desc = t["writing_task"]["description"].format(topic=topic)
        if revision_feedback:
            writing_desc += (
                f"\n\n【主编修改意见，必须逐条响应并修订】\n{revision_feedback}"
            )
        writing_task = Task(
            description=writing_desc,
            agent=self.writer,
            expected_output=t["writing_task"]["expected_output"],
            output_pydantic=ArticleOutput,
            context=[research_task, analysis_task],
        )

        # Process.sequential（顺序执行）
        # 所有 Task 按列表顺序一个接一个串行执行。
        # 每个 Task 的 context（依赖）通常指向前面已完成的 Task 输出
        # 每个 Task 由指定的 agent 执行，没有中间管理层
        # 简单、可预测、易调试，适合线性流水线，流程是"扁平"的：没有谁在协调谁
        #
        # Process.hierarchical（层级执行）
        # CrewAI 会自动创建一个"经理"(manager) Agent，由它来统筹调度
        # manager 自己不写内容，而是根据目标和 Task 列表，动态决定把哪个子任务派给哪个 agent、按什么顺序、是否需要迭代。
        # agent 之间可以并行、互相协作，manager 负责汇总与质量把关。
        # 适合复杂、任务间依赖不明确、需要灵活协调的多智能体场景。
        # 代价：行为不那么确定（每次调度可能不同）、更耗 token、需要 model 支持且通常要配 manager_llm、调试更复杂。
        crew = Crew(
            agents=[self.researcher, self.analyst, self.writer, self.editor],
            tasks=[research_task, analysis_task, writing_task],
            verbose=True,
            process=Process.sequential,
            tracing=True,  # CrewAI 原生 tracing：上报至 CrewAI AMP（依赖 CREWAI_API_KEY）
        )

        logger.info(f"[_run_crew] 开始编排 topic={topic} revision={'有' if revision_feedback else '无'}")
        result = crew.kickoff()
        logger.info(f"[_run_crew] 编排完成，输出长度={len(str(result))}")
        return str(result)

    def generate(self, topic: str, user: Optional[str] = None, revision_feedback: str = None) -> str:
        """对外主入口：包裹可观测性与重试。

        revision_feedback 不为空时，作为主编修改意见注入写作任务（定向重写）。
        """
        with trace_run("tech_media_crew", topic=topic, user=user):
            return self._run_crew(topic, revision_feedback=revision_feedback)



class EditorialFlow(Flow):
    """带审校回环的编辑流程。"""

    def __init__(self, crew: TechMediaCrew):
        super().__init__()
        self.crew = crew

    @start()
    def draft(self):
        self.state["topic"] = self.state.get("topic", "")
        # 首轮：直接走完整 Crew（含一次内审）
        logger.info("[editorial_flow] 首轮起草开始")
        self.state["draft"] = self.crew.generate(
            self.state["topic"], self.state.get("user")
        )
        logger.info("[editorial_flow] 首轮起草完成")

    @listen(draft)
    def review(self):
        # 主编基于草稿给出「是否合格 + 具体修改意见」。
        # 仅作门禁的硬规则（过短/占位符）也纳入，避免出现空意见时误判通过。
        draft: ArticleOutput = self.state.get("draft")
        text = draft.body if draft else ""
        hard_fail = len(text) < 300 or "待补充" in text

        t = self.crew.task_cfg
        review_task = Task(
            description=t["review_task"]["description"].format(article=text),
            agent=self.crew.editor,
            expected_output=t["review_task"]["expected_output"],
        )

        verdict = str(review_task.execute_sync() or "")
        self.state["feedback"] = verdict
        logger.info(f"主编建议：{verdict}")

        if hard_fail or "REVISE" in verdict.upper():
            self.state["needs_revision"] = True
        else:
            self.state["needs_revision"] = False
        logger.info(f"[editorial_flow] 审校结论: {'需重写' if self.state['needs_revision'] else '通过'}")


    @listen(review)
    def maybe_revise(self) -> ArticleOutput:
        rounds = self.state.get("rounds", 0)
        if self.state.get("needs_revision") and rounds < settings.max_revision_rounds:
            self.state["rounds"] = rounds + 1
            # 把主编的具体修改意见作为定向反馈，传给写作任务进行修订
            feedback = self.state.get("feedback", "")
            logger.info(f"[editorial_flow] 第 {rounds + 1} 轮重写，主编意见: {feedback[:200]}")

            self.state["draft"] = self.crew.generate(
                self.state["topic"], self.state.get("user"),
                revision_feedback=feedback,
            )
            return self.maybe_revise()
        else:
            logger.info(f"迭代次数达到最大值:{settings.max_revision_rounds}")

        return self.state.get("draft") or ArticleOutput()


def run_flow(topic: str, user: Optional[str] = None) -> ArticleOutput:
    """便捷函数：运行带审校回环的编辑流程，返回结构化 ArticleOutput。"""
    crew = TechMediaCrew()
    with trace_run("editorial_flow", topic=topic, user=user):
        flow = EditorialFlow(crew)
        flow.state["topic"] = topic
        flow.state["user"] = user
        flow.state["rounds"] = 0  # 从 0 开始计数，使审校回环真正生效
        return flow.kickoff()
