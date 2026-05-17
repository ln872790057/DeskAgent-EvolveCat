"""Read webpage content via HTTP GET. HTML cleaning, entity decoding, garbage removal."""
import re
import html as _html

from skills.pro_researcher.models import ResearchSource

USER_AGENT = "Mozilla/5.0 (compatible; PoisonCatResearchBot/2.5; +https://github.com/poisoncat)"
MAX_CONTENT_LENGTH = 12000

# Garbage patterns to remove after HTML extraction
GARBAGE_PATTERNS = [
    r'%PDF-[\d.]+',          # PDF binary header
    r'endobj|endstream|xref|trailer|startxref',  # PDF internal markers
    r'Skip to (content|main|footer|navigation)', # accessibility skip links
    r'(登录|注册|首页|关于我们|联系我们|隐私政策|用户协议|Cookie|Cookies)',
    r'Skip to main content',
    r'Skip to navigation',
]

# Navigation boilerplate to strip
NAV_BOILERPLATE = [
    "首页", "关于我们", "联系我们", "登录", "注册", "搜索",
    "Home", "About", "Contact", "Login", "Sign Up", "Search",
    "Skip to content", "Skip to main", "Skip to footer",
]


def clean_content(html_content: str) -> str:
    """Clean HTML content: decode entities, strip tags, remove garbage."""
    if not html_content:
        return ""

    # 1. HTML entity decode
    try:
        text = _html.unescape(html_content)
    except Exception:
        text = html_content

    # 2. Remove script/style/nav/footer/header blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # 4. Remove garbage patterns
    for pattern in GARBAGE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 5. Normalize whitespace
    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines = []
    previous = set()
    for line in lines:
        if not line:
            continue
        if len(line) <= 2:
            continue
        if line in NAV_BOILERPLATE:
            continue
        if line in previous:
            continue
        previous.add(line)
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 6. Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def read_source_content(source: ResearchSource, timeout: int = 10) -> ResearchSource:
    """Attempt to read the full page content for a source.
    Returns the source with read_status updated. Never raises.
    """
    source.accessed_at = __import__("datetime").datetime.now().isoformat()
    if not source.url or not source.url.startswith("http"):
        source.read_status = "failed"
        return source

    try:
        import httpx
        with httpx.Client(timeout=float(timeout), follow_redirects=True) as client:
            resp = client.get(
                source.url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
            )
            if resp.status_code == 200:
                text = resp.text
                # Detect PDF binary early
                if text.strip().startswith("%PDF-"):
                    source.read_status = "failed"
                    return source

                cleaned = clean_content(text)
                if len(cleaned) > 200:
                    source.content = cleaned[:MAX_CONTENT_LENGTH]
                    source.read_status = "full" if len(cleaned) <= MAX_CONTENT_LENGTH else "partial"
                else:
                    source.read_status = "snippet_only"
            else:
                source.read_status = "failed"
    except ImportError:
        source.read_status = "snippet_only"
    except Exception:
        source.read_status = "failed"

    return source


def read_multiple_sources(sources: list[ResearchSource], max_pages: int = 12, timeout: int = 10) -> list[ResearchSource]:
    """Read content for multiple sources, up to max_pages. Skips already-read sources."""
    read_count = 0
    for source in sources:
        if read_count >= max_pages:
            break
        if source.read_status not in ("unread",):
            continue
        read_source_content(source, timeout=timeout)
        read_count += 1
    return sources
