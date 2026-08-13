"""FastAPI 入口：纯后端 API 服务（前端独立启动并跨域调用）。"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat
from app.db.init_db import init_db
from app.observability.otel_setup import setup as setup_otel
from app.util.logger import get_logger, setup_logging

# 避免 Windows cmd 下 crewai tracing 输出 emoji 时报 gbk 编码错误
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 OpenLIT，使 CrewAI 的 LLM 调用自动通过 OTel 上报到 Langfuse
    setup_otel()
    # 数据库初始化
    init_db()
    logger.info("数据库初始化完成。")
    yield


app = FastAPI(title="技术媒体编辑部 Agent", version="0.1.0", lifespan=lifespan)

# 允许前端独立服务（如 vite dev server:5173）跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/")
def root():
    return {"msg": "技术媒体编辑部 Agent 后端已启动。", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
