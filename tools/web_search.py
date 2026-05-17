from utils.logger import get_logger

logger = get_logger()


def search_web(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=3):
                results.append(f"{r['title']}: {r['body'][:120]}")
        if not results:
            return "没找到相关信息"
        return "\n".join(results)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return "搜索失败"
