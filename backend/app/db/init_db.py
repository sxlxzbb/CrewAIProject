"""启动时初始化数据库：建表并插入默认账号。"""
from app.config.settings import settings
from app.db.database import engine, Base, SessionLocal
from app.db.models import User


def init_db() -> None:
    # 建表
    Base.metadata.create_all(bind=engine)

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
