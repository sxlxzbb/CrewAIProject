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
import json
import re
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
from crewai import LLM, Agent, Task
from crewai.flow.flow import Flow, listen, start
from crewai_tools import TavilySearchTool
from crewai.tools import tool as crewai_tool

from app.config.settings import settings
from app.observability.langfuse_client import trace_run
from app.util.logger import get_logger
from app.util.tools import get_current_time

logger = get_logger("crew")

# 配置目录：本文件所在 crew/ 的上一级的 config/
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


class ArticleOutput(BaseModel):
    """结构化产出：便于前端展示与下游入库。"""
    title: str = Field(default="", description="文章标题")
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


def _extract_article_from_raw(raw: str) -> "ArticleOutput | None":
    """
    从 Crew 的完整原始输出中提取 ArticleOutput。

    raw 通常是模型输出的 JSON（可能被 ```json 代码块包裹）。这里做最稳健的提取：
    1. 去掉 ```json ... ``` 代码块包裹；
    2. 尝试整段 json.loads；
    3. 尝试截取第一个 { ... } 块解析；
    4. 若 JSON 损坏，用正则分别提取 title/summary/body/keywords/confidence；
    5. 仍失败返回 None，由调用方兜底。
    """
    if not raw:
        return None

    text = raw.strip()

    # 去掉任意位置的 ```json ... ``` 代码块包裹（取第一个代码块内容）
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # 候选 1：去掉 fence 后的全文
    # 候选 2：第一个 { 到最后一个 } 之间的内容
    candidates = [text]
    try:
        start = text.index("{")
        end = text.rindex("}")
        candidates.append(text[start:end + 1])
    except ValueError:
        pass

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if not (data.get("body") or data.get("title")):
            continue
        return _dict_to_article(data)

    # JSON 损坏时的兜底：用正则尽量提取关键字段，保证 title/confidence 不丢
    return _extract_article_by_regex(text)


def _dict_to_article(data: dict) -> ArticleOutput:
    """把 dict 转换为 ArticleOutput，字段容错处理。"""
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    return ArticleOutput(
        title=(data.get("title") or "").strip(),
        summary=(data.get("summary") or "").strip(),
        body=(data.get("body") or "").strip(),
        keywords=keywords,
        confidence=float(data.get("confidence") or 0.0),
    )


def _extract_article_by_regex(text: str) -> "ArticleOutput | None":
    """当 JSON 解析失败时，用正则从文本中提取字段。

    用下一个 key 作为锚点，避免 body 内容中的引号提前截断匹配。
    """
    title_match = re.search(r'"title"\s*:\s*"(.*?)"\s*,\s*"summary"', text, re.DOTALL)
    summary_match = re.search(r'"summary"\s*:\s*"(.*?)"\s*,\s*"body"', text, re.DOTALL)
    confidence_match = re.search(r'"confidence"\s*:\s*([\d.]+)', text)

    # body 从 "body" 之后开始，贪婪匹配到 ", "keywords" 之前
    body_match = re.search(r'"body"\s*:\s*"(.*)"\s*,\s*"keywords"', text, re.DOTALL)

    # 如果关键字段都没匹配到，说明不是文章结构
    if not (title_match or body_match):
        return None

    def _unescape(s: str) -> str:
        if not s:
            return ""
        # 简单处理常见的 JSON 转义
        return (
            s.replace('\\n', '\n')
             .replace('\\"', '"')
             .replace('\\\\', '\\')
             .replace('\\t', '\t')
        )

    title = _unescape(title_match.group(1)) if title_match else ""
    summary = _unescape(summary_match.group(1)) if summary_match else ""
    body = _unescape(body_match.group(1)) if body_match else ""
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0

    keywords = []
    kw_match = re.search(r'"keywords"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if kw_match:
        kw_str = kw_match.group(1)
        keywords = re.findall(r'"(.*?)"', kw_str)

    return ArticleOutput(
        title=title.strip(),
        summary=summary.strip(),
        body=body.strip(),
        keywords=keywords,
        confidence=confidence,
    )


class TechMediaCrew:
    """简化版技术媒体编辑部（可落地封装）。"""

    def __init__(self):
        self._setup_llm()
        self._setup_editor_llm()
        self._setup_tools()
        self._load_config()
        self._build_agents()
        # 进度回写所需上下文（由 Flow / generate 在每次调用前设置）
        self.run_id: int = None
        self.round_no: int = 1  # 当前重写轮次（1 表示首轮）

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
        # logger.info(f"审校Agent LLM配置,model_name:{name},key:{key},base_url:{base_url},temp:{temp}")
        self.editor_llm = LLM(
            api_key=key,
            base_url=base_url,
            model=name,
            temperature=temp,
        )

    def _setup_tools(self):
        self.search_tool = TavilySearchTool(max_results=3)
        self.current_time_tool = crewai_tool(get_current_time)

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
            tools=[self.current_time_tool],
            **common,
        )

        self.editor = Agent(
            role=a["editor"]["role"],
            goal=a["editor"]["goal"],
            backstory=a["editor"]["backstory"],
            tools=[self.current_time_tool],
            **editor_common,
        )

    @_retry()
    def _run_crew(
        self,
        topic: str,
        revision_feedback: str = None,
        prefill_draft: str = None,
    ) -> ArticleOutput:
        t = self.task_cfg

        # 断点续跑：若提供已有草稿，则跳过搜索/分析，直接基于草稿写作/改写
        if prefill_draft:
            logger.info("[_run_crew] 使用预填草稿（跳过搜索/分析），直接进入写作")
            writing_desc = (
                t["writing_task"]["description"].format(topic=topic)
                + f"\n\n【已有草稿，请在此基础上完善/改写，保持结构与字段完整】\n{prefill_draft}"
            )

            if revision_feedback:
                writing_desc += (
                    f"\n\n【主编修改意见，必须逐条响应并修订】\n{revision_feedback}"
                )

            writing_task = Task(
                description=writing_desc,
                agent=self.writer,
                expected_output=t["writing_task"]["expected_output"],
                output_pydantic=ArticleOutput,
            )

            # 预填草稿场景：直接从撰写开始（基于已有草稿改写）
            tasks = [writing_task]

            step_keys = ["writing"]

        else:
            research_task = Task(
                description=t["research_task"]["description"].format(topic=topic),
                agent=self.researcher,
                expected_output=t["research_task"]["expected_output"],
            )

            analysis_task = Task(
                description=t["analysis_task"]["description"].format(topic=topic),
                agent=self.analyst,
                expected_output=t["analysis_task"]["expected_output"],
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
            )

            tasks = [research_task, analysis_task, writing_task]

            step_keys = ["researching", "analyzing", "writing"]

        # 手动按序执行每个 Task，并在【开始前】回写当前步骤，保证前端实时展示。
        # 不使用 crew.kickoff()，因为 CrewAI 的回调机制无法可靠区分当前执行到哪个 Agent。
        # 注意：task.execute_sync(context=...) 的 context 必须是【字符串】，不能传 TaskOutput 列表
        # （CrewAI 的 TaskStartedEvent.context 为 str 类型，传列表会校验失败）。
        logger.info(f"[_run_crew] 开始编排 topic={topic} revision={'有' if revision_feedback else '无'} prefill={'有' if prefill_draft else '无'}")
        last_output = None
        ctx_text = ""
        for step_key, task in zip(step_keys, tasks):
            try:
                from app.db import repository as repo
                repo.update_run_current_step(self.run_id, f"{step_key}#{self.round_no}")
            except Exception as e:
                logger.warning(f"[_run_crew] 步骤回写失败（已忽略）: {e}")

            # 仅把前面已完成的 Task 输出拼接为字符串，作为本 Task 的上下文
            last_output = task.execute_sync(context=ctx_text or None)
            logger.info(f"{step_key} last step output:{last_output}")
            ctx_text += ("\n\n" if ctx_text else "") + (getattr(last_output, "raw", None) or str(last_output))

        result = last_output  # 最后一个 Task（撰写）的输出即成品

        # 将 Task 输出稳健解析为结构化 ArticleOutput。
        # 注意：writing_task 输出的是含长正文（body）的大 JSON。
        # CrewAI 的 output_pydantic在解析超长字符串字段时可能截断/丢失内容，因此【优先使用 result.raw 完整原文】
        # 自己提取 body，确保主编审校时拿到的是完整正文。
        article: ArticleOutput
        if isinstance(result, ArticleOutput):
            article = result
        else:
            # 1) 优先从完整原始输出 raw 提取（最保真，不会被 pydantic 截断）
            raw_text = getattr(result, "raw", None)
            if raw_text:
                parsed = _extract_article_from_raw(raw_text)
                if parsed is not None:
                    article = parsed
                else:
                    # raw 无法解析为结构，直接把 raw 当作正文兜底
                    article = ArticleOutput(body=raw_text)
            elif hasattr(result, "pydantic") and result.pydantic is not None:
                # TaskOutput 配置了 output_pydantic 时，结构化结果在此
                try:
                    article = result.pydantic if isinstance(result.pydantic, ArticleOutput) else ArticleOutput(**result.pydantic)
                except Exception:
                    article = ArticleOutput(body=str(result))
            else:
                article = ArticleOutput(body=str(result))

        logger.info(f"[_run_crew] 第{self.round_no}轮编排完成，标题={article.title} 置信度={article.confidence}")
        return article


    def generate(
        self,
        topic: str,
        user: Optional[str] = None,
        revision_feedback: str = None,
        prefill_draft: str = None,
        run_id: int = None,
        round_no: int = 1,
    ) -> ArticleOutput:
        """
        对外主入口：包裹可观测性与重试。
        :param topic:
        :param user:
        :param revision_feedback: 不为空时，作为主编修改意见注入写作任务（定向重写）。
        :param prefill_draft: 搜索/分析/首轮草稿的过程落库（断点续跑场景下 prefill 阶段不写这些）
        :param run_id: 非空时，将每步产物写入 review_logs 实现过程持久化。
        :param round_no: 当前重写轮次（0 表示首轮），用于进度回调的 #轮次 后缀。
        :return:
        """
        # 进度回写上下文（供 _run_crew 手动编排时按步骤回写使用）
        self.run_id = run_id
        self.round_no = round_no

        # 搜索/分析/首轮草稿的过程落库（断点续跑场景下 prefill 阶段不写这些）
        # if run_id and not prefill_draft:
        #     from app.db import repository as repo
        #     try:
        #         # research/analysis 内容在 Crew 内部，此处仅标记阶段开始；
        #         # 草稿正文在 draft 产出后由 Flow 写 step='draft'
        #         repo.add_review_log(run_id, step="research", content=f"开始调研主题：{topic}", round=0)
        #
        #         repo.add_review_log(run_id, step="analysis", content="开始分析调研结果", round=0)
        #     except Exception as e:
        #         logger.exception(f"[generate] 过程日志写入失败（已忽略）")

        with trace_run("tech_media_crew", topic=topic, user=user):
            return self._run_crew(topic, revision_feedback=revision_feedback, prefill_draft=prefill_draft)



class EditorialFlow(Flow):
    """带审校回环的编辑流程。"""

    def __init__(self, crew: TechMediaCrew):
        super().__init__()
        self.crew = crew

    @start()
    def draft(self):
        topic = self.state.get("topic")
        if not topic:
            raise ValueError('topic不能为空')

        user = self.state.get("user")
        run_id = self.state.get("run_id")
        prefill = self.state.get("prefill_draft")
        round_no = self.state.get('rounds', 1)

        # 首轮：若有预填草稿则跳过搜索/分析（断点续跑）
        logger.info(f"[editorial_flow] 首轮起草开始,{topic=}")

        self.state["draft"] = self.crew.generate(topic, user,
            prefill_draft=prefill, run_id=run_id, round_no=round_no,
        )

        # 落库首轮草稿
        if run_id:
            from app.db import repository as repo
            try:
                draft = self.state["draft"]
                body = draft.body if isinstance(draft, ArticleOutput) else str(draft)
                repo.add_review_log(run_id, step="draft", content=body, round=round_no)
            except Exception as e:
                logger.exception(f"[draft] 草稿日志写入失败")

        logger.info("[editorial_flow] 首轮起草完成")


    def _run_review(self, round_idx: int) -> str:
        """执行一轮审校：运行审校 Task，设置 needs_revision，并落库 review 日志。

        返回主编意见（verdict 文本）。供首轮 review 节点与回环内的重写后审校共用，
        确保每一轮（含最后一轮即使不通过）的审校结论都被持久化。
        """
        run_id = self.state.get("run_id")
        if run_id:
            from app.db import repository as repo
            repo.update_run_current_step(run_id, f"editing#{round_idx}")

        draft = self.state.get("draft")
        # 容错：draft 可能为 ArticleOutput 或历史遗留的字符串
        if isinstance(draft, ArticleOutput):
            text = draft.body or ""
        else:
            text = draft or ""

        # 基础校验
        hard_fail = len(text) < 100 or "待补充" in text

        # 审校task配置
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
        logger.info(f"[editorial_flow] 第 {round_idx} 轮审校结论: {'需重写' if self.state['needs_revision'] else '通过'}")

        # 落库本轮回环的审校结论（即使达到最大次数不通过也照常保存）
        run_id = self.state.get("run_id")
        if run_id:
            from app.db import repository as repo
            try:
                repo.add_review_log(
                    run_id, step="review",
                    content=verdict,
                    round=round_idx,  # 轮数
                    verdict="REVISE" if self.state["needs_revision"] else "PASS",
                    needs_revision=self.state["needs_revision"],
                )
            except Exception as e:
                logger.exception(f"[_run_review] 审校日志写入失败（已忽略）")

        return verdict


    @listen(draft)
    def review(self):
        # 首轮审校（round 0）
        self._run_review(round_idx=self.state.get("rounds", 1))


    @listen(review)
    def maybe_revise(self) -> ArticleOutput:
        run_id = self.state.get("run_id")
        # 重写+再审校 的回环：每轮重写后都重新走真实审校并落库，
        # 直到通过或达到最大循环次数（最后一轮即使不通过也会保存审校意见）。
        while self.state.get("needs_revision") and self.state.get("rounds") < settings.max_revision_rounds:
            # 当前轮数
            current_rounds = self.state.get("rounds", 1)
            feedback = self.state.get("feedback", "")
            logger.info(f"[editorial_flow] 第 {current_rounds} 轮，主编意见: {feedback[:200]}")

            # 断点续跑：基于上一轮草稿（含主编意见）直接改写，避免重新从搜索开始，
            # 否则审校就失去了意义（审校是针对草稿提意见，重写应在草稿基础上修改）。
            prev_draft = self.state.get("draft")
            prefill = prev_draft.body if isinstance(prev_draft, ArticleOutput) else (prev_draft or None)

            self.state["rounds"] = current_rounds + 1

            # 下一轮生成，从上一轮草稿的基础上修改
            self.state["draft"] = self.crew.generate(
                self.state["topic"], self.state.get("user"),
                revision_feedback=feedback, run_id=run_id,
                prefill_draft=prefill, round_no=self.state["rounds"],
            )

            # 落库本轮重写后的草稿
            if run_id:
                from app.db import repository as repo
                try:
                    draft = self.state["draft"]
                    body = draft.body if isinstance(draft, ArticleOutput) else str(draft)
                    repo.add_review_log(run_id, step="draft", content=body, round=self.state["rounds"])
                except Exception as e:
                    logger.exception(f"[maybe_revise] 草稿日志写入失败（已忽略）")

            # 重写后重新审校（落库审校意见，更新 needs_revision）
            self._run_review(round_idx=self.state["rounds"])

        if self.state.get("needs_revision"):
            logger.info(f"迭代次数达到最大值:{settings.max_revision_rounds}，最终审校未通过（意见已保存）")

        return self.state.get("draft") or ArticleOutput()


def run_flow(
    topic: str,
    user: Optional[str] = None,
    run_id: int = None,
    prefill_draft: str = None,
) -> ArticleOutput:
    """便捷函数：运行带审校回环的编辑流程，返回结构化 ArticleOutput。

    run_id 非空时，流程过程会写入 review_logs（持久化）。
    prefill_draft 提供已有草稿时跳过搜索/分析（断点续跑用）。
    """
    crew = TechMediaCrew()
    with trace_run("editorial_flow", topic=topic, user=user):
        flow = EditorialFlow(crew)
        flow.state["topic"] = topic
        flow.state["user"] = user
        flow.state["rounds"] = 1  # 第一轮
        flow.state["run_id"] = run_id
        flow.state["prefill_draft"] = prefill_draft # 先不用已有草稿
        return flow.kickoff()
