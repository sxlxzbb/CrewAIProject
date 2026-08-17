"""数据库会话与连接管理（SQLAlchemy）。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config.settings import settings


class Base(DeclarativeBase):
    pass


# 这儿engine已经带了连接池（QueuePool）
# pool_size=5（常驻连接数）
# max_overflow=10（高峰时最多再临时开 10 个）
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 取出连接前先 ping 一下，避免拿到失效连接
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# 关闭的时会话
def get_db():
    """FastAPI 依赖：提供请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        # 把连接归还给池
        db.close()
