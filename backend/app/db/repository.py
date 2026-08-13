"""持久化访问层：封装 generation_runs / review_logs / articles 的读写。

每个函数内部独立创建并关闭数据库会话，保证在 CrewAI Flow 的线程环境中调用也是线程安全的。
不使用数据库外键约束，关联通过 run_id 字段逻辑维护（见 models.py 注释）。
"""
from datetime import datetime

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import GenerationRun, ReviewLog, Article
from app.crew.article_crew import ArticleOutput


def create_run(topic: str, author: str) -> int:
    """创建一条运行记录，返回 run_id（状态初始为 RUNNING）。"""
    db = SessionLocal()
    try:
        run = GenerationRun(topic=topic, author=author, status="RUNNING")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def update_run(
    run_id: int,
    status: str = None,
    rounds: int = None,
    error: str = None,
    finished_at: datetime = None,
    duration_ms: int = None,
) -> None:
    """更新运行记录的状态/轮次/错误/结束信息。"""
    db = SessionLocal()
    try:
        # 这儿返回的run是受 session 跟踪的 ORM 实例，修改它的字段 + commit() 就等价于 UPDATE
        run = db.get(GenerationRun, run_id)
        if run is None:
            return
        if status is not None:
            run.status = status
        if rounds is not None:
            run.rounds = rounds
        if error is not None:
            run.error = error
        if finished_at is not None:
            run.finished_at = finished_at
        if duration_ms is not None:
            run.duration_ms = duration_ms
        db.commit()
    finally:
        db.close()


def add_review_log(
    run_id: int,
    step: str,
    content: str,
    round: int = 0,
    verdict: str = None,
    needs_revision: bool = None,
) -> int:
    """追加一条过程明细（搜索/分析/写作/审校的每一步）。返回日志 id。"""
    db = SessionLocal()
    try:
        log = ReviewLog(
            run_id=run_id,
            round=round,
            step=step,
            content=content,
            verdict=verdict,
            needs_revision=needs_revision,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log.id
    finally:
        db.close()


def get_latest_draft(run_id: int) -> str | None:
    """取该 run 最新一轮的草稿正文（用于断点续跑：跳过搜索/分析，从写作继续）。"""
    db = SessionLocal()
    try:
        stmt = (
            select(ReviewLog.content)
            .where(ReviewLog.run_id == run_id, ReviewLog.step == "draft")
            .order_by(ReviewLog.round.desc(), ReviewLog.id.desc())
            .limit(1)
        )
        row = db.execute(stmt).scalar_one_or_none()
        return row
    finally:
        db.close()


def get_run(run_id: int) -> GenerationRun | None:
    """查询运行记录。"""
    db = SessionLocal()
    try:
        return db.get(GenerationRun, run_id)
    finally:
        db.close()


def save_article(run_id: int, article: ArticleOutput, author: str, topic: str) -> int:
    """落库最终结构化文章，并与 run 关联（run_id 唯一）。"""
    db = SessionLocal()
    try:
        rec = Article(
            run_id=run_id,
            title=article.title or "无标题",
            summary=article.summary or "",
            body=article.body or "",
            keywords=article.keywords or [],
            confidence=article.confidence or 0.0,
            author=author,
            topic=topic,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec.id
    finally:
        db.close()
