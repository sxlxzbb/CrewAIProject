"""聊天/生成路由：接收主题，返回编辑部最终成文。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import decode_token
from app.db.database import get_db
from app.crew.article_crew import run_flow

logger = logging.getLogger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


class TopicRequest(BaseModel):
    topic: str


def _get_current_user(auth: str = Depends(decode_token)):
    return auth


@router.post("/generate")
def generate(req: TopicRequest, username: str = Depends(_get_current_user), db: Session = Depends(get_db)):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="主题不能为空")
    try:
        result = run_flow(topic, user=username)
    except Exception as e:
        logger.exception("[chat] 生成失败")
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")
    return {"topic": topic, "result": result, "author": username}
