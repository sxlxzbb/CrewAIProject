"""ORM 模型定义。"""
import hashlib

from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(String(64), nullable=False)  # md5 哈希

    @staticmethod
    def md5(raw: str) -> str:
        """对明文密码做 MD5（兼容既有约定，生产建议加盐）。"""
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
