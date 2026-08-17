"""后台任务执行体：在子进程中运行 Flow 并落库。

本模块的函数会被 ProcessPoolExecutor 序列化后送入子进程执行，因此：
- 不能依赖主进程的全局状态（DB session / MCP client 实例）；
- 所有资源在子进程内自行初始化（每次调用都新建 crew、建 DB 连接）。
"""
import os
import sys
from datetime import datetime

# 确保子进程能找到项目根（Windows 下 spawn 启动方式需要）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.db import repository as repo
from app.crew.article_crew import run_flow
from app.crew.article_crew import ArticleOutput
from app.config.settings import settings
from app.util import mcp_client
from app.util.logger import get_logger

logger = get_logger("worker")


def _publish(run_id: int, article: ArticleOutput) -> str:
    """调用 MCP 发布，返回工具原始结果（形如 {"code":0,"message":"success"}）。"""
    return mcp_client.publish_article(article)


def _should_skip(run_id: int) -> bool:
    """任务被取消时，后续写状态应跳过，避免覆盖 CANCELLED。"""
    run = repo.get_run(run_id)
    return run is None or run.status == "CANCELLED"


def run_generate_task(run_id: int, topic: str, username: str, prefill_draft: str = None):
    """首轮 / 重写 / 续跑 共用的后台执行体。

    由进程池调用，负责：置 RUNNING → 跑 Flow → 落 article → 置 SUCCESS/FAILED。
    prefill_draft 非空时从写作续跑（跳过搜索/分析）。
    """
    # 若任务在启动前已被取消，直接结束
    if _should_skip(run_id):
        logger.info(f"[worker] 任务 {run_id} 已被取消，跳过执行")
        return

    # 复用调用方（/generate 或 /review?action=regenerate）已写入的 current_step（如 researching#1），
    # 不传 current_step 会把它清成 None，导致进度卡片短暂显示「排队中」
    repo.update_run(run_id, status="RUNNING", error=None, finished_at=None, duration_ms=None,
                    current_step="researching#1")

    start = datetime.now()
    try:
        result: ArticleOutput = run_flow(
            topic=topic, user=username, run_id=run_id,
            prefill_draft=prefill_draft,
        )
        # 跑完后若被取消，不再落库/发布（但 review_logs 里已记录的过程产物保留）
        if _should_skip(run_id):
            logger.info(f"[worker] 任务 {run_id} 跑完后发现已被取消，不覆盖状态")
            return

        # 落库
        repo.save_article(run_id, result, author=username, topic=topic)

        # 未开启人工审核的话自动发布
        if not settings.require_human_review:
            publish_result = _publish(run_id, result)
            repo.update_article_review(run_id, review_status=-1, publish_result=publish_result)

        repo.update_run(
            run_id, status="SUCCESS", rounds=0,
            finished_at=datetime.now(),
            duration_ms=int((datetime.now() - start).total_seconds() * 1000),
        )
        logger.info(f"[worker] 任务 {run_id} 完成")
    except Exception as e:
        if _should_skip(run_id):
            logger.info(f"[worker] 任务 {run_id} 异常但已被取消，不覆盖状态")
            return

        repo.update_run(run_id, status="FAILED", error=str(e)[:2000],
                        finished_at=datetime.now(),
                        duration_ms=int((datetime.now() - start).total_seconds() * 1000))

        logger.exception(f"[worker] 任务 {run_id} 失败")
