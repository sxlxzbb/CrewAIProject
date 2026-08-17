"""聊天/生成路由：接收主题，异步提交生成任务，并落库运行记录与文章。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import decode_token
from app.config.settings import settings
from app.db.database import get_db
from app.db import repository as repo
from app.crew.article_crew import ArticleOutput
from app.util import mcp_client
from app.util.logger import get_logger
from app.worker.pool import get_executor
from app.worker import tasks as worker_tasks

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


class TopicRequest(BaseModel):
    topic: str


def _get_current_user(auth: str = Depends(decode_token)):
    return auth


def _publish_article(run_id: int, article: ArticleOutput) -> str:
    """调用 MCP 发布文章，直接返回发布工具的结果（形如 {"code":0,"message":"success"}），不做额外包装；失败则抛出异常。"""
    return mcp_client.publish_article(article)


class ReviewRequest(BaseModel):
    action: str  # approve=通过并发布 / reject=放弃 / regenerate=重新生成


@router.post("/generate")
def generate(req: TopicRequest, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """
    文章生成（异步）：仅创建任务并返回 run_id，后台进程池执行。

    前端拿到 run_id 后轮询 GET /api/tasks/{run_id} 获取进度与结果。
    """
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="主题不能为空")

    run_id = repo.create_run(topic, username)  # status=PENDING
    get_executor().submit(worker_tasks.run_generate_task, run_id, topic, username, None)
    require_review = settings.require_human_review
    return {"topic": topic, "author": username, "run_id": run_id,
            "status": "PENDING", "require_review": require_review}


@router.post("/review/{run_id}")
def review(run_id: int, req: ReviewRequest, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """人工审核接口：对生成完成的文章进行 通过/放弃/重新生成。"""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    article = repo.get_article_by_run_id(run_id)
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")

    action = (req.action or "").strip().lower()
    if action == "approve":
        # 仅允许「已成功生成」的任务发布；非 SUCCESS 状态（如进行中/失败/取消）不发布，仅记日志
        if run.status != "SUCCESS":
            logger.warning(
                f"[chat] 审核通过被拒绝：run_id={run_id} 当前状态为 {run.status}，非 SUCCESS，不执行发布"
            )
            return {"run_id": run_id, "action": action, "published": False,
                    "msg": f"任务状态为 {run.status}，尚未成功生成，无法发布"}

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
        # 重新生成：异步提交后台任务（复用同一 run_id，review_logs 按新 round 追加）
        if run.status == "RUNNING":
            raise HTTPException(status_code=400, detail="任务进行中，无法重新生成")

        # 用户主动点击重新生成：不带上一轮草稿，从「搜索→分析→写作」完整重新生成
        # （仅自动回环 maybe_revise 才带上一轮草稿，用户手动 regenerate 一律从头开始）
        # prefill = None
        # repo.update_run(run_id, status="RUNNING", error=None, finished_at=None, duration_ms=None,
        #                 current_step="researching#1")
        get_executor().submit(worker_tasks.run_generate_task, run_id, run.topic, username)
        return {"run_id": run_id, "action": action, "published": False,
                "msg": "已提交重新生成，请轮询进度", "require_review": settings.require_human_review}

    raise HTTPException(status_code=400, detail=f"未知审核动作: {req.action}")


@router.post("/generate/retry/{run_id}")
def retry(run_id: int, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """
    断点续跑（异步）：对某个运行记录重新执行。
    """
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status == "RUNNING":
        raise HTTPException(status_code=400, detail="任务进行中，无法重试")

    topic = run.topic
    # 复用已有草稿实现「从写作继续」
    # prefill = repo.get_latest_draft(run_id)

    # repo.update_run(run_id, status="RUNNING", error=None, finished_at=None, duration_ms=None, current_step="researching#1")
    get_executor().submit(worker_tasks.run_generate_task, run_id, topic, username)
    require_review = settings.require_human_review
    return {"topic": topic, "author": username, "run_id": run_id, "status": "RUNNING", "require_review": require_review}


@router.get("/tasks/{run_id}")
def task_status(run_id: int, db: Session = Depends(get_db)):
    """轮询任务进度：返回状态、当前步骤、轮次、成品（SUCCESS 时）。"""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    article = None
    if run.status == "SUCCESS":
        art = repo.get_article_by_run_id(run_id)
        if art is not None:
            article = {
                "title": art.title,
                "summary": art.summary,
                "body": art.body,
                "keywords": art.keywords,
                "confidence": art.confidence,
                "review_status": art.review_status,
                "publish_result": art.publish_result,
            }

    return {
        "run_id": run_id,
        "status": run.status,
        "current_step": run.current_step,
        "rounds": run.rounds,
        "error": run.error,
        "article": article,
        "require_review": settings.require_human_review,
        "review_status": article["review_status"] if article else None,
    }


@router.post("/tasks/{run_id}/cancel")
def cancel_task(run_id: int, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    """
    取消任务：仅允许取消 PENDING/RUNNING 的任务，并记录为 CANCELLED。

    注意：CrewAI 子进程中的模型调用无法被真正强行终止（Python future 对已开始任务
    的 cancel() 无效），因此该接口为"软取消"——前端停止轮询，后端标记为已取消；
    子进程跑完后若发现状态已为 CANCELLED，不会再覆盖为 SUCCESS/FAILED。
    """
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status not in ("PENDING", "RUNNING"):
        raise HTTPException(status_code=400, detail=f"当前任务状态为 {run.status}，无法取消")

    repo.update_run(run_id, status="CANCELLED", error=None, finished_at=datetime.now(),
                    duration_ms=int((datetime.now() - run.created_at).total_seconds() * 1000))
    return {"run_id": run_id, "status": "CANCELLED"}
