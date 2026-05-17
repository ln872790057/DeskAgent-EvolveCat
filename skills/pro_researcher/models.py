"""Structured data models for research results."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ResearchSource:
    title: str
    url: str
    domain: str = ""
    snippet: str = ""
    content: str = ""
    published_at: Optional[str] = None
    accessed_at: str = ""
    source_type: str = "unknown"  # official|paper|github|tech_blog|industry_report|media|self_media|pr|unknown
    quality: str = "C"            # S|A|B|C
    read_status: str = "unread"   # full|partial|snippet_only|failed
    usable_for_core: bool = True
    quality_reason: str = ""


@dataclass
class ResearchClaim:
    claim: str
    claim_type: str = "fact"      # fact|analysis|risk|opinion|recommendation
    source_urls: list = field(default_factory=list)
    confidence: str = "low"       # high|medium|low
    support_count: int = 0
    contradicting_urls: list = field(default_factory=list)
    caveat: str = ""


@dataclass
class EvidenceItem:
    source_id: str
    url: str
    title: str = ""
    source_type: str = "unknown"
    quality: str = "C"
    excerpt: str = ""
    supports: list = field(default_factory=list)


@dataclass
class ResearchEvent:
    title: str
    summary: str
    category: str = "综合动态"
    event_time: str = "待核验"
    source_urls: list = field(default_factory=list)
    importance: str = "medium"    # high|medium|low
    certainty: str = "likely"     # confirmed|likely|unverified
    why_it_matters: str = ""
    affected_parties: list = field(default_factory=list)
    evidence: list = field(default_factory=list)


@dataclass
class ResearchReport:
    topic: str
    depth: int = 3
    research_type: str = "general"  # news|technical|product|company|policy|controversy|general
    one_line_conclusion: str = ""
    confidence: str = "低"
    time_range: str = ""
    sources: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    events: list = field(default_factory=list)
    top_events: list = field(default_factory=list)
    evidence_items: list = field(default_factory=list)
    key_findings: list = field(default_factory=list)
    editorial_summary: str = ""
    timeline_content: str = ""
    tech_analysis: str = ""
    business_analysis: str = ""
    risks_and_controversies: str = ""
    sassy_comment: str = ""
    recommendation: str = ""
    watchlist: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    review_passed: bool = True
    review_score: int = 100
    review_issues: list = field(default_factory=list)
    review_actions: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def read_success_count(self) -> int:
        return sum(1 for s in self.sources if s.read_status in ("full", "partial"))

    @property
    def read_success_ratio(self) -> float:
        return self.read_success_count / max(len(self.sources), 1)
