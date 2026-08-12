"""本地运行日志（轻量可观测性）。

说明：CrewAI 原生已集成 Langfuse —— 只要在 .env 配置
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 且设 CREWAI_TRACING_ENABLED=true，
CrewAI 运行时会自动把每个 Agent/Task 的调用、输入输出、token、耗时上报到 Langfuse，
无需手写上报代码（与 LangChain + LangSmith 体验一致）。

本模块只保留"本地日志降级"：记录每次运行的开始/完成/耗时/异常，便于排查，
不调用任何 Langfuse SDK，绝不影响主流程。
"""
import time
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("observability")


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
