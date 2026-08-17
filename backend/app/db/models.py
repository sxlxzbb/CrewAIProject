"""ORM 模型定义。"""
import hashlib

from sqlalchemy import String, Integer, BigInteger, Float, JSON, Text, DateTime, func
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


class GenerationRun(Base):
    """生成任务运行记录（任务级概要，任务级断点续跑的载体）。

    关联说明（不使用数据库外键约束，仅逻辑关联）：
    - review_logs.run_id        → 本表 id（一对多，记录该任务每一步过程）
    - articles.run_id           → 本表 id（一对一，记录该任务最终成品；失败任务无对应 article）
    """
    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(255), index=True, nullable=False, comment="生成主题")
    author: Mapped[str] = mapped_column(String(64), index=True, nullable=False, comment="发起用户名")

    # 状态枚举: PENDING / RUNNING / SUCCESS / FAILED / CANCELLED
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="PENDING",
                                         comment="任务状态 PENDING/RUNNING/SUCCESS/FAILED/CANCELLED")
    # 当前执行步骤：大步骤(draft/review/maybe_revise) + 小步骤(researching/analyzing/writing/editing) + 轮次(#N)
    current_step: Mapped[str] = mapped_column(String(32), nullable=True, index=True,
                                              comment="当前执行步骤 draft/review/maybe_revise + researching/writing... + #轮次")
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="实际重写轮次")
    error: Mapped[str] = mapped_column(Text, nullable=True, comment="失败原因（FAILED 时填写）")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment="任务开始时间")
    finished_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True, comment="任务结束时间")
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=True, comment="耗时（毫秒）")


class ReviewLog(Base):
    """编辑流程全过程明细（按轮次/步骤展开的时间线）。

    一个任务从 搜索→分析→写作→审校 的每一步都在此表追加一行，
    按 (run_id, round, step) 排序即可完整回放该任务的执行过程。

    关联说明（不使用数据库外键约束，仅逻辑关联）：
    - run_id → generation_runs.id
    """
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 逻辑外键：指向 generation_runs.id（不使用数据库外键约束）
    run_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="关联 generation_runs.id")

    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                       comment="回环轮次：research/analysis 为 0，draft/review 随重写递增")
    # step 枚举: research / analysis / draft / review
    step: Mapped[str] = mapped_column(String(16), index=True, nullable=False,
                                      comment="步骤 research/analysis/draft/review")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="该步骤主要产物（搜索结果/分析/草稿正文等）")

    # 仅 review 步骤使用
    verdict: Mapped[str] = mapped_column(String(16), nullable=True, comment="审校结论 PASS / REVISE（仅 review 步骤）")
    needs_revision: Mapped[bool] = mapped_column(nullable=True, comment="是否需要重写（仅 review 步骤）")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment="该步骤完成时间")


class Article(Base):
    """最终产出文章（结构化，便于前端展示与下游消费）。

    关联说明（不使用数据库外键约束，仅逻辑关联）：
    - run_id → generation_runs.id（一对一；失败任务无对应记录，故可空）
    """
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 逻辑外键：指向 generation_runs.id（不使用数据库外键约束），成功任务一一对应，失败任务无记录
    run_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=True,
                                        comment="关联 generation_runs.id（一对一，可空）")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="文章标题")
    summary: Mapped[str] = mapped_column(Text, nullable=True, comment="文章摘要（100字内）")
    body: Mapped[str] = mapped_column(Text, nullable=False, comment="文章正文")
    keywords: Mapped[list] = mapped_column(JSON, nullable=True, comment="关键词列表")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
                                             comment="置信度 0~1（内容可信/完整程度）")
    author: Mapped[str] = mapped_column(String(64), index=True, nullable=False, comment="作者/发起用户")
    topic: Mapped[str] = mapped_column(String(255), index=True, nullable=False, comment="生成主题")

    # 人工审核状态：0=待审核(默认) 1=通过 2=放弃
    review_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                               index=True, comment="人工审核状态 0待审核/1通过/2放弃")
    # 发布结果：通过审核自动发布后，写入 MCP 工具返回的 result(JSON 字符串)；未发布则空
    publish_result: Mapped[str] = mapped_column(String(200), nullable=True,
                                                comment="MCP 发布工具返回结果(JSON)，未发布为空")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment="成文时间")
