"""FastAPI 入口：纯后端 API 服务（前端独立启动并跨域调用）。"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat
from app.db.init_db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="技术媒体编辑部 Agent", version="0.1.0")

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


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("数据库初始化完成。")


@app.get("/")
def root():
    return {"msg": "技术媒体编辑部 Agent 后端已启动。", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
