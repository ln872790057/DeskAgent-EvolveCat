import webbrowser

from utils.logger import get_logger

logger = get_logger()


def open_url(url: str) -> str:
    # URL validation: only http/https
    url_lower = url.strip().lower()
    if not url_lower.startswith(("http://", "https://")):
        url = "https://" + url
        url_lower = "https://" + url_lower

    if not url_lower.startswith(("http://", "https://")):
        return "只能打开http/https链接"

    try:
        webbrowser.open(url)
        return f"已打开：{url}"
    except Exception as e:
        logger.error(f"Open URL failed: {e}")
        return "打开网页失败"
