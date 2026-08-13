"""聊天/生成路由：接收主题，返回编辑部最终成文，并落库运行记录与文章。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import decode_token
from app.db.database import get_db
from app.db import repository as repo
from app.crew.article_crew import run_flow
from app.util.logger import get_logger

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


class TopicRequest(BaseModel):
    topic: str


def _get_current_user(auth: str = Depends(decode_token)):
    return auth


def _persist_success(run_id: int, topic: str, username: str, result, start: datetime):
    """流程成功后落库文章并更新 run 状态。"""
    try:
        repo.save_article(run_id, result, author=username, topic=topic)
        repo.update_run(
            run_id,
            status="SUCCESS",
            rounds=0,  # 实际轮次以 review_logs 为准，这里保留兼容
            finished_at=datetime.now(),
            duration_ms=int((datetime.now() - start).total_seconds() * 1000),
        )
    except Exception as e:
        logger.warning(f"[chat] 成功后续写库失败（已忽略）: {e}")


@router.post("/generate")
def generate(req: TopicRequest, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """
    文章生成
    :param req:
    :param username:
    :param db:
    :return:
    """
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="主题不能为空")

    run_id = repo.create_run(topic, username)
    start = datetime.now()
    try:
        result = run_flow(topic, user=username, run_id=run_id)
    except Exception as e:
        repo.update_run(run_id, status="FAILED", error=str(e)[:2000],
                        finished_at=datetime.now(),
                        duration_ms=int((datetime.now() - start).total_seconds() * 1000))
        logger.exception("[chat] 生成失败")
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")

    _persist_success(run_id, topic, username, result, start)
    return {"topic": topic, "result": result, "author": username, "run_id": run_id}


@router.post("/generate/retry/{run_id}")
def retry(run_id: int, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """
    断点续跑：对某个运行记录重新执行。

    若该 run 已落过草稿（review_logs step='draft'），则跳过搜索/分析，
    直接基于已有草稿进入写作/审校（从写作继续）。否则从头重跑。
    """
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status == "RUNNING":
        raise HTTPException(status_code=400, detail="任务进行中，无法重试")

    topic = run.topic
    # 复用已有草稿实现「从写作继续」
    prefill = repo.get_latest_draft(run_id)

    # 重置该 run 的状态与过程（保留历史 review_logs 便于对比，可选清理）
    repo.update_run(run_id, status="RUNNING", error=None, finished_at=None, duration_ms=None)
    start = datetime.now()
    try:
        result = run_flow(topic, user=username, run_id=run_id, prefill_draft=prefill)
    except Exception as e:
        repo.update_run(run_id, status="FAILED", error=str(e)[:2000],
                        finished_at=datetime.now(),
                        duration_ms=int((datetime.now() - start).total_seconds() * 1000))
        logger.exception("[chat] 重试失败")
        raise HTTPException(status_code=500, detail=f"重试失败: {e}")

    _persist_success(run_id, topic, username, result, start)
    return {"topic": topic, "result": result, "author": username, "run_id": run_id}
