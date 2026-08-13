"""认证路由：登录签发 JWT。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt  # 轻量 JWT
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.database import get_db
from app.db.models import User
from app.util.logger import get_logger

logger = get_logger("auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(request: Request) -> str:
    """从 Authorization: Bearer <token> 头解析 JWT，返回用户名；失败抛 401。"""
    from fastapi import status
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization token",
        )
    token = auth[len("Bearer "):].strip()
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return data["sub"]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的凭证",
        )


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or user.password != User.md5(form.password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = _create_token(user.username)
    return {"access_token": token, "token_type": "bearer", "username": user.username}
