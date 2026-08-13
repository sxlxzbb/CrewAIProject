"""通用工具：可被 CrewAI Agent 挂载为工具函数。"""
from datetime import datetime, timezone, timedelta


def get_current_time() -> str:
    """获取当前时间（北京时间，UTC+8）以及 UTC 时间。

    涉及时效性判断（如"最新发版时间""距今多久""某某版本是否已发布"）时，
    请以本工具返回的当前时间为准，不要依据训练知识中的日期猜测。
    返回格式示例：
        北京时间 2026-08-13 15:30:45 (UTC+8) | UTC 2026-08-13 07:30:45
    """
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now.astimezone(timezone(timedelta(hours=8)))
    return (
        f"北京时间 {bj_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8) | "
        f"UTC {utc_now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
