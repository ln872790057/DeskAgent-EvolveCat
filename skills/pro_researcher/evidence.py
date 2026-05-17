"""Source grading, claim confidence, cross-validation, report confidence."""
from skills.pro_researcher.models import ResearchSource, ResearchClaim, ResearchReport


def estimate_claim_confidence(claim: ResearchClaim, sources: list[ResearchSource]) -> str:
    """Estimate confidence level for a claim based on supporting sources."""
    url_to_source = {s.url: s for s in sources}

    s_count = 0  # S-level sources supporting this claim
    a_count = 0  # A-level
    for url in claim.source_urls:
        src = url_to_source.get(url)
        if not src:
            continue
        if src.quality == "S":
            s_count += 1
        elif src.quality == "A":
            a_count += 1

    has_contradiction = bool(claim.contradicting_urls)
    high_quality = s_count + a_count

    # high: >=3 independent S/A sources, no contradiction
    # medium: 1-2 S/A sources, no contradiction
    # low: single source, self-media, unverified, or contradiction

    if high_quality >= 3 and not has_contradiction:
        return "high"
    if high_quality >= 1 and not has_contradiction:
        return "medium"
    return "low"


def check_cross_validation(claims: list[ResearchClaim], sources: list[ResearchSource]) -> list[ResearchClaim]:
    """Check each claim for independent source support and contradictions."""
    url_to_source = {s.url: s for s in sources}

    for claim in claims:
        # Count independent (different domain) supporting sources
        domains = set()
        for url in claim.source_urls:
            src = url_to_source.get(url)
            if src:
                domains.add(src.domain)
        claim.support_count = len(domains)

        # Estimate confidence
        claim.confidence = estimate_claim_confidence(claim, sources)

    # Detect contradictions between claims
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            c1, c2 = claims[i], claims[j]
            words1 = set(c1.claim.lower().split())
            words2 = set(c2.claim.lower().split())
            overlap = len(words1 & words2) / max(len(words1 | words2), 1)
            if overlap < 0.3:
                continue
            if c1.claim_type == c2.claim_type:
                continue
            # Potential contradiction: mark both
            if c1.confidence != "high":
                c1.contradicting_urls.extend(c2.source_urls[:1])
            if c2.confidence != "high":
                c2.contradicting_urls.extend(c1.source_urls[:1])

    return claims


def estimate_report_confidence(report: ResearchReport) -> str:
    """Calculate overall report confidence."""
    sources = report.sources
    claims = report.claims
    if not sources:
        return "低"

    full_ratio = report.read_success_ratio
    high_quality_ratio = sum(1 for s in sources if s.quality in ("S", "A")) / max(len(sources), 1)
    low_claim_ratio = sum(1 for c in claims if c.confidence == "low") / max(len(claims), 1) if claims else 0

    if full_ratio >= 0.6 and high_quality_ratio >= 0.4 and low_claim_ratio <= 0.25:
        return "高"
    if full_ratio >= 0.35 and high_quality_ratio >= 0.2:
        return "中"
    return "低"
