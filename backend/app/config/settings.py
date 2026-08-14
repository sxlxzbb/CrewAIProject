"""全局配置：从 .env 读取，集中管理密钥与连接信息。

所有配置项均通过环境变量（.env）注入，代码中不再保留敏感或环境相关的默认值
（仅保留类型兜底用的空值/占位，实际运行时必须由 .env 提供）。
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 模型（字段名 -> 环境变量名 映射）
    model_name: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""
    temperature: float = 0.7
    max_iter: int = 3  # 放开迭代，允许 Agent 自我纠正（带守卫）

    # 审校智能体(主编)专用模型：未配置时回退使用上面的主模型配置
    editor_model_name: str = ""
    editor_dashscope_api_key: str = ""
    editor_dashscope_base_url: str = ""
    editor_temperature: float = 0.7

    # CrewAI Flow最大重写次数：「写 → 审 → 改」回环 ----
    max_revision_rounds: int = 3

    # 搜索工具
    tavily_api_key: str = ""

    # 数据库
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""

    # Langfuse 可观测性
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # 安全
    jwt_secret: str = ""
    jwt_expire_minutes: int = 1440

    # CrewAI AMP 认证（用于绑定账号的正式 trace 上报，避免匿名 ephemeral）
    crewai_api_key: str = ""

    # 默认账号（启动建表时插入）
    default_username: str = ""
    default_password: str = ""

    # MCP 服务（Java Spring AI MCP，StreamableHTTP）
    mcp_base_url: str = ""
    mcp_auth_token: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


settings = Settings()
