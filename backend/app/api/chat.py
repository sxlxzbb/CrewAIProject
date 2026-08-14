"""聊天/生成路由：接收主题，返回编辑部最终成文，并落库运行记录与文章。"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import decode_token
from app.config.settings import settings
from app.db.database import get_db
from app.db import repository as repo
from app.crew.article_crew import run_flow
from app.crew.article_crew import ArticleOutput
from app.util import mcp_client
from app.util.logger import get_logger

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


class TopicRequest(BaseModel):
    topic: str


def _get_current_user(auth: str = Depends(decode_token)):
    return auth


def _publish_article(run_id: int, article: ArticleOutput) -> str:
    """调用 MCP 发布文章，返回发布工具结果 JSON 字符串；失败则抛出异常。"""
    result = mcp_client.publish_article(article)
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def _persist_success(run_id: int, topic: str, username: str, result, start: datetime):
    """流程成功后落库文章并更新 run 状态。

    若开启人工审核（默认）：仅落库，review_status=0 待审核，不自动发布；
    若关闭人工审核：生成完成后直接通过 MCP 自动发布并记录结果。
    """
    try:
        repo.save_article(run_id, result, author=username, topic=topic)

        publish_result = None
        review_status = 0  # 待审核
        if not settings.require_human_review:
            # 无需人工审核：直接发布，审核状态记为 -1（人工审核未开启）
            publish_result = _publish_article(run_id, result)
            review_status = -1
            repo.update_article_review(run_id, review_status=review_status, publish_result=publish_result)

        repo.update_run(
            run_id,
            status="SUCCESS",
            rounds=0,  # 实际轮次以 review_logs 为准，这里保留兼容
            finished_at=datetime.now(),
            duration_ms=int((datetime.now() - start).total_seconds() * 1000),
        )
    except Exception as e:
        logger.warning(f"[chat] 成功后续写库/发布失败（已忽略）: {e}")


class ReviewRequest(BaseModel):
    action: str  # approve=通过并发布 / reject=放弃 / regenerate=重新生成


@router.post("/review/{run_id}")
def review(run_id: int, req: ReviewRequest, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """人工审核接口：对生成完成的文章进行 通过/放弃/重新生成。"""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status != "SUCCESS":
        raise HTTPException(status_code=400, detail="任务尚未生成完成，无法审核")

    article = repo.get_article_by_run_id(run_id)
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")

    action = (req.action or "").strip().lower()
    if action == "approve":
        # 通过：自动发布，写入发布结果。审核状态：未开启审核记 -1，否则记 1
        target_status = -1 if not settings.require_human_review else 1
        if article.review_status in (1, -1) and article.publish_result:
            return {"run_id": run_id, "action": action, "published": True,
                    "publish_result": article.publish_result, "msg": "此前已发布，无需重复"}
        try:
            publish_result = _publish_article(run_id, ArticleOutput(
                title=article.title, summary=article.summary, body=article.body,
                keywords=article.keywords, confidence=article.confidence,
            ))
        except Exception as e:
            logger.exception("[chat] 审核通过-发布失败")
            raise HTTPException(status_code=500, detail=f"发布失败: {e}")
        repo.update_article_review(run_id, review_status=target_status, publish_result=publish_result)
        return {"run_id": run_id, "action": action, "published": True, "publish_result": publish_result}

    elif action == "reject":
        # 放弃：不发布，review_status=2
        repo.update_article_review(run_id, review_status=2, publish_result=None)
        return {"run_id": run_id, "action": action, "published": False, "msg": "已放弃，未发布"}

    elif action == "regenerate":
        # 重新生成：复用断点续跑逻辑（从写作继续），不更新审核字段（生成后仍需审核）
        prefill = repo.get_latest_draft(run_id)
        repo.update_run(run_id, status="RUNNING", error=None, finished_at=None, duration_ms=None)
        start = datetime.now()
        try:
            result = run_flow(topic=run.topic, user=username, run_id=run_id, prefill_draft=prefill)
        except Exception as e:
            repo.update_run(run_id, status="FAILED", error=str(e)[:2000],
                            finished_at=datetime.now(),
                            duration_ms=int((datetime.now() - start).total_seconds() * 1000))
            logger.exception("[chat] 重新生成失败")
            raise HTTPException(status_code=500, detail=f"重新生成失败: {e}")
        _persist_success(run_id, run.topic, username, result, start)
        return {"run_id": run_id, "action": action, "published": False,
                "msg": "已重新生成，待人工审核", "result": result,
                "require_review": settings.require_human_review,
                "review_status": 0 if settings.require_human_review else 1}

    raise HTTPException(status_code=400, detail=f"未知审核动作: {req.action}")


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
    require_review = settings.require_human_review
    return {"topic": topic, "result": result, "author": username, "run_id": run_id,
            "require_review": require_review,
            "review_status": 0 if require_review else 1}


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
    require_review = settings.require_human_review
    return {"topic": topic, "result": result, "author": username, "run_id": run_id,
            "require_review": require_review,
            "review_status": 0 if require_review else 1}
