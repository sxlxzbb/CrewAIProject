"""启动时初始化数据库：建表并插入默认账号。"""
from sqlalchemy import inspect, text

from app.config.settings import settings
from app.db.database import engine, Base, SessionLocal
from app.db.models import User


def _ensure_generation_runs_columns() -> None:
    """对已存在的 generation_runs 表做增量加列（create_all 不会改已有表）。

    仅补充本迭代新增的 current_step 字段；若已存在则跳过。
    """
    inspector = inspect(engine)
    if "generation_runs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("generation_runs")}
    needed = {
        "current_step": "VARCHAR(32) NULL",
    }
    with engine.begin() as conn:
        for col, ddl in needed.items():
            if col not in cols:
                conn.execute(text(f"ALTER TABLE generation_runs ADD COLUMN {col} {ddl}"))


def init_db() -> None:
    # 建表
    Base.metadata.create_all(bind=engine)
    # 兼容已部署库：增量补列
    _ensure_generation_runs_columns()

    username = settings.default_username
    password = settings.default_password
    if not username or not password:
        print("[init_db] 警告: .env 未配置 DEFAULT_USERNAME / DEFAULT_PASSWORD，跳过默认账号插入。")
        return

    # 插入默认账号（若不存在）
    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.username == username).first()
        if not exists:
            db.add(
                User(
                    username=username,
                    password=User.md5(password),
                )
            )
            db.commit()
            print(f"[init_db] 已创建默认账号: {username} / {password}")
        else:
            print("[init_db] 默认账号已存在，跳过插入。")
    finally:
        db.close()
