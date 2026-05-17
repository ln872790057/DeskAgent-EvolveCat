import re
import threading
from datetime import datetime, timedelta

from PySide6.QtCore import QTimer

from utils.logger import get_logger

logger = get_logger()


def parse_time(time_str: str) -> int:
    """Parse natural language time string to seconds from now."""
    now = datetime.now()

    # "10分钟后"
    m = re.search(r"(\d+)\s*分钟\s*后", time_str)
    if m:
        return int(m.group(1)) * 60

    # "2小时后"
    m = re.search(r"(\d+)\s*小时\s*后", time_str)
    if m:
        return int(m.group(1)) * 3600

    # "明天上午9点"
    m = re.search(r"明天.*?(\d+)\s*点", time_str)
    if m:
        target = now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0) + timedelta(days=1)
        return max(0, int((target - now).total_seconds()))

    # "下午3点" or "3点" (today)
    m = re.search(r"(\d+)\s*点", time_str)
    if m:
        hour = int(m.group(1))
        if "下午" in time_str or "晚上" in time_str:
            hour = hour + 12 if hour < 12 else hour
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(0, int((target - now).total_seconds()))

    # "30秒后"
    m = re.search(r"(\d+)\s*秒\s*后", time_str)
    if m:
        return int(m.group(1))

    # Default: 10 minutes
    logger.warning(f"Could not parse time: {time_str}, defaulting to 10min")
    return 600


def set_reminder(time_str: str, content: str) -> str:
    try:
        delay_sec = parse_time(time_str)
        target_time = datetime.now() + timedelta(seconds=delay_sec)
        target_str = target_time.strftime("%H:%M")

        def trigger():
            try:
                from plyer import notification
                notification.notify(
                    title="deskagent提醒",
                    message=content,
                    timeout=10,
                )
            except Exception:
                pass  # Silent fail if notification not available

        QTimer.singleShot(int(delay_sec * 1000), trigger)
        return f"已设置提醒：{content}，将在{target_str}提醒你"
    except Exception as e:
        logger.error(f"Reminder failed: {e}")
        return "设置提醒失败"
