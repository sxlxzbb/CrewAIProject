"""统一日志工具：定义带时间戳的日志格式，供全局复用。

日志格式示例：
    2026-08-13 14:30:05 [INFO] [crew] 开始编排 topic=AI
"""
import logging

# 时间格式：年-月-日 时:分:秒
_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """配置 root logger 的格式与级别（只需在程序入口调用一次）。"""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler()
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # 清空已有 handler，避免重复输出（如 basicConfig 已添加）
    root.handlers.clear()
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式的子 logger。

    若尚未调用 setup_logging，会先按默认级别初始化，保证单独引用也能有时间戳。
    """
    if not _configured:
        setup_logging()
    return logging.getLogger(name)
