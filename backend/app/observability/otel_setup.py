"""OpenTelemetry / OpenLIT 初始化：把 CrewAI 的 trace 自动上报到 Langfuse。

说明：
- CrewAI 1.15 原生 tracing 只走 CrewAI AMP（依赖 CREWAI_API_KEY）。
- 要让 trace 同时进入 Langfuse，使用 OpenLIT 对 LLM 调用做 OpenTelemetry 自动埋点，
  并通过 Langfuse 的 OTLP HTTP endpoint 接收数据。
- 本模块根据 .env 中的 LANGFUSE_* 自动计算 OTEL 所需的 endpoint 与 headers。
"""
import base64
import os

from app.config.settings import settings
from app.util.logger import get_logger

logger = get_logger("observability")


def setup_langfuse_otel() -> bool:
    """若 .env 中配置了 Langfuse key，则设置 OTEL exporter 环境变量并返回 True。"""
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    if not pk or not sk:
        logger.info("[otel_setup] 未配置 LANGFUSE_PUBLIC_KEY/SECRET_KEY，跳过 Langfuse OTel 设置。")
        return False

    host = (settings.langfuse_host or "https://cloud.langfuse.com").rstrip("/")
    endpoint = f"{host}/api/public/otel"
    auth = base64.b64encode(f"{pk}:{sk}".encode("utf-8")).decode("ascii")
    headers = f"Authorization=Basic {auth},x-langfuse-ingestion-version=4"

    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    os.environ.setdefault("OTEL_EXPORTER_OTLP_HEADERS", headers)
    # Langfuse 的 OTLP endpoint 只接收 traces，禁用 logs/metrics 避免 404
    os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
    logger.info(f"[otel_setup] 已配置 OTEL endpoint: {endpoint}")
    return True


def init_openlit() -> None:
    """初始化 OpenLIT 自动埋点（失败静默）。"""
    try:
        import openlit
        openlit.init(disable_batch=True)
        logger.info("[otel_setup] OpenLIT 初始化完成，LLM 调用将自动上报 Langfuse。")
    except Exception as e:
        logger.warning(f"[otel_setup] OpenLIT 初始化失败（已忽略）: {e}")


def setup() -> None:
    """一键设置并初始化。"""
    if setup_langfuse_otel():
        init_openlit()
