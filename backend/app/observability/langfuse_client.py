"""本地运行日志（可观测性的轻量兜底）。

说明：
- CrewAI 1.15 的原生 tracing 只上报到 CrewAI AMP（依赖 CREWAI_API_KEY），
  并不会读取 LANGFUSE_* 或自动发往 Langfuse。因此这里不再手写 Langfuse 埋点
  （手写埋点既不可靠也偏离「无缝衔接」的预期）。
- 若以后要在 Langfuse 中查看，标准做法是配置 litellm 的 Langfuse callback，
  让底层 LLM 调用自动上报，而非在业务代码里手动打点。
- 本模块只做「开始/完成/异常 + 耗时」的本地日志，对主流程零侵入、零副作用。
"""
import time
from contextlib import contextmanager
from typing import Optional

from app.util.logger import get_logger

logger = get_logger("observability")


@contextmanager
def trace_run(name: str, topic: str, user: Optional[str] = None):
    """上下文管理器：包裹一次完整运行，仅记录本地日志。"""
    start = time.time()
    meta = {"topic": topic, "user": user or "anonymous"}
    logger.info(f"[trace] 开始 {name} | topic={topic} user={user}")
    try:
        yield meta   # 这里执行 with 代码块里的内容
        cost = time.time() - start
        logger.info(f"[trace] 完成 {name} | 耗时={cost:.1f}s")
    except Exception as e:
        cost = time.time() - start
        logger.error(f"[trace] 失败 {name} | 耗时={cost:.1f}s | err={e}")
        raise
