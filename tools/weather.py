import urllib.request
import urllib.parse

from utils.logger import get_logger

logger = get_logger()


def get_weather(city: str) -> str:
    try:
        encoded = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded}?format=3"
        req = urllib.request.Request(url, headers={"User-Agent": "curl"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode("utf-8").strip()
        if not result:
            return f"查不到{city}的天气"
        return result
    except Exception as e:
        logger.error(f"Weather failed: {e}")
        return "天气查询失败"
