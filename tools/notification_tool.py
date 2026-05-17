from utils.logger import get_logger

logger = get_logger()


def show_notification(title: str, content: str) -> str:
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=content,
            timeout=5,
        )
        return "已发送通知"
    except Exception as e:
        logger.error(f"Notification failed: {e}")
        return "发送通知失败"
