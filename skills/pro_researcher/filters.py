"""Content filtering and source deduplication rules."""
import re
from urllib.parse import urlparse

from skills.pro_researcher.models import ResearchSource

BLACKLIST_DOMAINS = {"prnewswire.com", "businesswire.com", "globenewswire.com"}
AGGREGATOR_DOMAINS = {
    "coaio.com", "unifuncs.com", "imfounder.com", "dentro.de",
    "tianqi.csdn.net", "k.sina.com.cn", "sina.cn", "hao.cnyes.com",
    "baike.baidu.com", "51diaocha.com", "fxbaogao.com", "chyxx.com",
    "tw.news.yahoo.com",
}
OFFICIAL_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "blog.google", "googleblog.com",
    "microsoft.com", "nvidia.com", "meta.com", "ai.meta.com", "apple.com",
    "sec.gov", "ftc.gov", "europa.eu", "gov.cn", "whitehouse.gov",
    "modelcontextprotocol.io", "cursor.com", "anthropic.com", "docs.anthropic.com",
    "docs.cursor.com", "docs.github.com", "cloudflare.com", "ibm.com",
    "cninfo.com.cn", "szse.cn", "sse.com.cn",
}
AUTHORITY_MEDIA_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "technologyreview.com", "theverge.com", "wired.com", "techcrunch.com",
    "mit.edu", "stanford.edu", "nature.com", "science.org",
}
SELF_MEDIA_DOMAINS = {
    "zhihu.com", "zhuanlan.zhihu.com", "jianshu.com", "toutiao.com",
    "mp.weixin.qq.com", "csdn.net", "juejin.cn", "bilibili.com",
    "youtube.com", "reddit.com", "x.com", "twitter.com", "facebook.com",
    "vocus.cc", "linkedin.com",
}
LOW_VALUE_TITLE_PATTERNS = [
    r"research\s*\|\s*release$",
    r"^openai research",
    r"^home\s*[\\|/-]",
    r"^home$",
    r"^research\s*[—|-]",
    r"^publications\s*[—|-]",
    r"newsroom\s*[\\|/-]\s*product",
    r"^首页$",
    r"^搜索",
    r"最新.*网站.*推荐",
    r"top\s*\d+.*announcements",
    r"release notes",
    r"(日报|晚新闻|早晚报|完整摘要|链接汇总|新闻汇总)",
    r"(daily|weekly)\s+(roundup|brief|digest)",
    r"(中译版|翻译稿|万字中译版)",
]
PR_KEYWORDS = [
    "公关稿", "通稿", "签约", "战略合作", "隆重发布", "重磅发布",
    "赋能", "引领行业", "生态共赢",
]
CLICKBAIT_PATTERNS = [r"震惊", r"惊呆", r"突然", r"刚刚", r"彻底爆了", r"全网都在"]
MIN_CONTENT_CHARS = 300


def normalize_url(url: str) -> str:
    """Remove fragments, query strings, and trailing slashes for dedup."""
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return normalized.lower()


def _domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in candidates)


def deduplicate_sources(sources: list[ResearchSource]) -> list[ResearchSource]:
    """Remove duplicate URLs. Keep the first occurrence."""
    seen = set()
    result = []
    for s in sources:
        norm = normalize_url(s.url)
        if norm not in seen:
            seen.add(norm)
            result.append(s)
    return result


def is_clickbait(title: str) -> bool:
    for pattern in CLICKBAIT_PATTERNS:
        if re.search(pattern, title):
            return True
    return False


def is_pr_content(text: str) -> bool:
    score = 0
    for kw in PR_KEYWORDS:
        if kw in text:
            score += 1
    return score >= 2


def classify_source_type(title: str, url: str, snippet: str = "", content: str = "") -> str:
    """Classify source type from title/URL/content hints."""
    combined = (title + " " + snippet + " " + content[:500]).lower()
    url_lower = url.lower()
    domain = urlparse(url).netloc.lower().removeprefix("www.")

    if _domain_matches(domain, AGGREGATOR_DOMAINS):
        return "aggregator"
    if "github.com" in domain:
        return "github"
    if any(d in domain for d in BLACKLIST_DOMAINS) or is_pr_content(combined):
        return "pr"
    if "arxiv.org" in domain or "doi.org" in domain or "论文" in combined or "paper" in combined:
        return "paper"
    if _domain_matches(domain, OFFICIAL_DOMAINS) or domain.endswith(".gov") or domain.endswith(".edu"):
        return "official"
    if any(part in url_lower for part in ["/docs/", "/documentation/", "/spec", "/api/"]) and storable_domain(domain):
        return "official"
    if _domain_matches(domain, SELF_MEDIA_DOMAINS):
        return "self_media"
    if any(kw in domain for kw in ["engineering.", "developers.", "developer.", "tech.", "dev.", "blog."]):
        return "tech_blog"
    if "medium.com" in domain or "substack.com" in domain:
        return "tech_blog"
    if _domain_matches(domain, AUTHORITY_MEDIA_DOMAINS):
        return "media"
    if any(kw in combined for kw in ["报告", "白皮书", "行业分析", "market report", "industry report"]):
        return "industry_report"
    if any(kw in combined for kw in ["新闻", "报道", "news"]):
        return "media"
    return "unknown"


def storable_domain(domain: str) -> bool:
    """Avoid classifying social/aggregator docs-like URLs as official."""
    return not (_domain_matches(domain, SELF_MEDIA_DOMAINS) or _domain_matches(domain, AGGREGATOR_DOMAINS))


def is_low_value_source(source: ResearchSource) -> bool:
    """Detect navigation, index, SEO, and weak sources that should not drive analysis."""
    return low_value_reason(source) != ""


def low_value_reason(source: ResearchSource) -> str:
    """Return a reason when a source should not drive core analysis."""
    title = (source.title or "").strip().lower()
    text = f"{source.title} {source.snippet} {source.content[:800]}".lower()
    parsed = urlparse(source.url)
    domain = (source.domain or parsed.netloc).lower().removeprefix("www.")
    path = (parsed.path or "/").rstrip("/") or "/"
    if _domain_matches(domain, AGGREGATOR_DOMAINS):
        return "聚合/转载站点"
    if any(re.search(pattern, title, re.I) for pattern in LOW_VALUE_TITLE_PATTERNS):
        return "泛化标题或索引页标题"
    if _is_official_index_path(domain, path):
        return "官网首页/索引页"
    if text.count("skip to main") or text.count("skip to content"):
        return "导航内容残留"
    nav_hits = sum(1 for kw in ["business", "developers", "company", "research", "login", "sign up"] if kw in text[:500])
    if nav_hits >= 5 and len(source.content or source.snippet) < 1200:
        return "疑似导航页"
    if source.source_type in ("self_media", "aggregator") and source.read_status in ("unread", "failed", "snippet_only"):
        return "低质量来源且未读到正文"
    return ""


def _is_official_index_path(domain: str, path: str) -> bool:
    """Official listing pages are useful background but should not be core events."""
    if not _domain_matches(domain, OFFICIAL_DOMAINS | AUTHORITY_MEDIA_DOMAINS):
        return False
    normalized = path.lower().rstrip("/") or "/"
    if normalized in {"/", "/research", "/publications", "/news", "/blog", "/index", "/product", "/products"}:
        return True
    blocked = {
        "openai.com": ["/news/product-releases", "/research/index/release", "/index"],
        "anthropic.com": ["/news", "/research", "/"],
        "deepmind.google": ["/research", "/research/publications", "/blog"],
        "blog.google": ["/innovation-and-ai", "/products"],
    }
    return any(normalized == p.rstrip("/") for p in blocked.get(domain, []))


def mark_source_quality(source: ResearchSource) -> ResearchSource:
    """Populate quality and core-eligibility fields consistently."""
    source.quality = grade_source_quality(source)
    reason = low_value_reason(source)
    if reason:
        source.usable_for_core = False
        source.quality_reason = reason
        source.quality = "C"
        return source
    if source.source_type in ("self_media", "aggregator", "pr"):
        source.usable_for_core = False
        source.quality_reason = "仅可作背景来源"
    elif source.read_status not in ("full", "partial"):
        source.usable_for_core = False
        source.quality_reason = "未读取到正文，不能支撑核心结论"
    elif source.read_status == "failed" and source.source_type not in ("official", "paper", "media"):
        source.usable_for_core = False
        source.quality_reason = "正文读取失败"
    else:
        source.usable_for_core = True
        source.quality_reason = ""
    return source


def grade_source_quality(source: ResearchSource) -> str:
    """Assign S/A/B/C quality grade to a source."""
    st = source.source_type
    domain = (source.domain or urlparse(source.url).netloc).lower().removeprefix("www.")

    if is_low_value_source(source):
        return "C"
    if st in ("official", "paper"):
        if source.read_status == "full":
            return "S"
        if source.read_status == "partial":
            return "A"
        return "B"
    if st == "github":
        return "A" if source.read_status in ("full", "partial") else "B"
    if st in ("tech_blog", "industry_report"):
        return "A" if source.read_status == "full" else "B"
    if st == "media":
        return "A" if _domain_matches(domain, AUTHORITY_MEDIA_DOMAINS) and source.read_status in ("full", "partial") else "B"
    if st == "self_media":
        return "C" if source.read_status == "snippet_only" else "B"
    if st in ("pr", "aggregator"):
        return "C"
    if is_clickbait(source.title):
        return "C"
    if len(source.content or source.snippet) < MIN_CONTENT_CHARS:
        return "C"
    return "B"
