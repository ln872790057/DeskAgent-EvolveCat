"""Markdown report template and user reply template."""
import os
import re
import sys
from datetime import datetime

from skills.pro_researcher.models import ResearchEvent, ResearchReport

REPORT_TYPE_LABELS = {
    "news": "新闻日报",
    "technical": "技术研究",
    "product": "产品竞品",
    "company": "公司行业",
    "policy": "政策监管",
    "controversy": "争议核验",
    "general": "通用研究",
}

USER_REPLY_TEMPLATE = """调研完成 📊

【摘要】
- 一句话结论：{one_line_conclusion}
- 置信度：{confidence}
- 事件卡片：{event_count} 个，Top事件：{top_count} 个
- 信息来源：{source_count} 个，正文读取成功：{read_success_count} 个
- 关键提醒：{main_caveat}

报告已保存到桌面：📄 {file_path}
{fallback_notice}"""


def safe_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    safe = re.sub(r"\s+", "_", safe).strip("._ ")
    return safe[:max_len] or "untitled"


def get_desktop_dir() -> tuple[str, str]:
    """Return (desktop_path, fallback_notice). Cross-platform."""
    candidates = []
    if sys.platform == "win32":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(os.path.join(userprofile, "Desktop"))
        candidates.append(os.path.join(os.path.expanduser("~"), "Desktop"))
    else:
        candidates.append(os.path.expanduser("~/Desktop"))
    for path in candidates:
        if path and os.path.exists(path):
            return path, ""
    return os.getcwd(), "桌面路径找不到，已保存到当前目录"


def save_report_to_desktop(report: ResearchReport, content: str) -> tuple[str, str]:
    """Save report to desktop. Returns (file_path, fallback_notice)."""
    safe_topic = safe_filename(report.topic)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"调研_{safe_topic}_{timestamp}.md"
    target_dir, fallback_notice = get_desktop_dir()
    file_path = os.path.join(target_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path, fallback_notice


def render_report(report: ResearchReport) -> str:
    """Render a ResearchReport to event-centric Markdown."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    quality = _quality_counts(report)

    sections = [
        f"# {report.topic} 调研报告",
        "",
        "## 今日摘要",
        report.editorial_summary or report.one_line_conclusion or "本次调研已完成事件聚类，详见下方事件卡片。",
        "",
        f"- 调研类型：{REPORT_TYPE_LABELS.get(report.research_type, '通用研究')}",
        f"- 一句话结论：{report.one_line_conclusion or '见事件卡片'}",
        f"- 调研时间：{ts}",
        f"- 信息来源：{report.source_count} 个（S级 {quality['S']} / A级 {quality['A']} / B级 {quality['B']} / C级 {quality['C']}）",
        f"- 正文读取：{report.read_success_count} 个来源成功读取",
        f"- 整体置信度：{report.confidence}",
        "",
        "## 核心结论与关键条目",
        _render_quality_warning(report),
        "",
        _render_top_events(report),
        "",
        "## 主体分析",
        _render_events_by_category(report.events, report.sources),
        "",
        "## 关键趋势判断",
        report.tech_analysis or report.recommendation or "趋势判断见上方事件卡片。",
        "",
        "## 风险与争议",
        report.risks_and_controversies or "未发现明确风险；单来源信息仍需继续核验。",
        "",
        "## 后续追踪清单",
        _render_watchlist(report),
        "",
        "## 方法说明",
        _render_method_note(report),
        "",
        f"---\n生成时间：{ts}",
    ]
    return "\n".join(sections)


def _render_quality_warning(report: ResearchReport) -> str:
    if getattr(report, "review_passed", True):
        return ""
    issues = getattr(report, "review_issues", []) or []
    actions = getattr(report, "review_actions", []) or []
    lines = [
        "## 质量审核提示",
        "",
        f"- 审核状态：未完全通过，评分 {getattr(report, 'review_score', 0)} / 100。",
        "- 使用建议：下面内容已正常输出，但请把涉及关键数字、强判断或单一来源的条目当作待核验草稿。",
    ]
    if issues:
        lines.append("- 主要问题：" + "；".join(str(item) for item in issues[:4]))
    if actions:
        lines.append("- 建议补强：" + "；".join(str(item) for item in actions[:4]))
    return "\n".join(lines)


def _render_top_events(report: ResearchReport) -> str:
    if not report.top_events:
        return "未形成可排序的核心条目。"
    blocks = []
    for i, event in enumerate(report.top_events, 1):
        blocks.append(_render_event_card(event, report.sources, index=i))
    return "\n\n".join(blocks)


def _render_events_by_category(events: list[ResearchEvent], sources: list) -> str:
    if not events:
        return "未形成事件聚类。"
    grouped = {}
    for event in events:
        grouped.setdefault(event.category or "综合动态", []).append(event)
    parts = []
    for category, items in grouped.items():
        parts.append(f"### {category}")
        for event in items:
            refs = _source_refs(event.source_urls, sources)
            parts.append(f"- **{event.title}**：{event.summary} {refs}".rstrip())
            if event.why_it_matters:
                parts.append(f"  - 影响判断：{event.why_it_matters}")
            if event.evidence:
                parts.append(f"  - 关键依据：{'；'.join(event.evidence[:2])}")
    return "\n".join(parts)


def _render_event_card(event: ResearchEvent, sources: list, index: int | None = None) -> str:
    refs = _source_refs(event.source_urls, sources)
    title = f"### {index}. {event.title}" if index else f"### {event.title}"
    affected = "、".join(event.affected_parties) if event.affected_parties else "待判断"
    evidence = "\n".join(f"- {item}" for item in event.evidence[:3] if item)
    if not evidence:
        evidence = "- 证据见来源编号。"
    return "\n".join([
        title,
        f"- 维度：{event.category}",
        f"- 时间：{event.event_time}",
        f"- 重要性：{_importance_label(event.importance)}；确定性：{_certainty_label(event.certainty)}",
        "",
        f"**核心内容**：{event.summary} {refs}".rstrip(),
        "",
        f"**编辑判断**：{event.why_it_matters or '该条目可能影响相关参与方的产品、策略或判断。'}",
        "",
        f"- 影响对象：{affected}",
        "- 证据：",
        evidence,
    ])


def _render_watchlist(report: ResearchReport) -> str:
    items = report.watchlist or ["继续补充官方公告、论文、监管文件或权威媒体交叉验证。"]
    return "\n".join(f"- {item}" for item in items[:8])


def _render_evidence_table(report: ResearchReport) -> str:
    if not report.evidence_items:
        return "暂无证据表。"
    lines = ["| 编号 | 质量 | 类型 | 支持事件 | 摘要 |", "|---|---|---|---|---|"]
    for item in report.evidence_items[:24]:
        supports = "；".join(item.supports[:2]) if item.supports else "背景来源"
        lines.append(
            f"| {item.source_id} | {item.quality} | {item.source_type} | "
            f"{_escape_table(supports[:80])} | {_escape_table(item.excerpt[:160])} |"
        )
    return "\n".join(lines)


def _render_sources(report: ResearchReport) -> str:
    lines = []
    for i, s in enumerate(report.sources, 1):
        status = {"full": "全文", "partial": "部分", "snippet_only": "摘要", "failed": "失败"}.get(s.read_status, s.read_status)
        core = "正文" if getattr(s, "usable_for_core", True) else f"背景：{getattr(s, 'quality_reason', '') or '低优先级'}"
        lines.append(f"[S{i}] [{s.quality}/{s.source_type}/{status}/{core}] {s.title[:100]} - {s.url}")
    return "\n".join(lines) if lines else "暂无来源。"


def _render_method_note(report: ResearchReport) -> str:
    notes = [
        "本报告先识别调研类型，再分面搜索、读取来源、抽取条目，最后生成证据链与编辑判断。",
        "官方、论文、监管文件、公司博客和权威媒体优先级高于自媒体与转载源。",
        "少于两个独立来源且非官方确认的热点传闻，会被标为较低确定性。",
    ]
    if report.limitations:
        notes.extend(f"局限：{item}" for item in report.limitations[:3])
    return "\n".join(f"- {item}" for item in notes)


def _source_refs(urls: list[str], sources: list) -> str:
    if not urls:
        return ""
    url_to_id = {s.url: f"S{i}" for i, s in enumerate(sources, 1)}
    refs = [f"[{url_to_id[url]}]" for url in urls if url in url_to_id]
    return "".join(refs)


def _quality_counts(report: ResearchReport) -> dict:
    return {q: sum(1 for s in report.sources if s.quality == q) for q in ("S", "A", "B", "C")}


def _escape_table(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def _render_sources(report: ResearchReport) -> str:
    """Render a compact source note without dumping every URL into the report."""
    evidence_urls = {item.url for item in report.evidence_items}
    selected = [
        (i, s) for i, s in enumerate(report.sources, 1)
        if s.url in evidence_urls or getattr(s, "usable_for_core", True)
    ][:12]
    lines = []
    for i, s in selected:
        status = {"full": "全文", "partial": "部分", "snippet_only": "摘要", "failed": "失败"}.get(s.read_status, s.read_status)
        core = "正文" if getattr(s, "usable_for_core", True) else f"背景：{getattr(s, 'quality_reason', '') or '低优先级'}"
        lines.append(f"[S{i}] [{s.quality}/{s.source_type}/{status}/{core}] {s.title[:100]}（{s.domain}）")
    if report.source_count > len(selected):
        lines.append(f"- 其余 {report.source_count - len(selected)} 个检索来源已省略，完整来源保存在任务过程产物中。")
    return "\n".join(lines) if lines else "暂无来源。"


def _importance_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value or "中")


def _certainty_label(value: str) -> str:
    return {"confirmed": "已确认", "likely": "较可信", "unverified": "待核验"}.get(value, value or "较可信")


def render_user_reply(report: ResearchReport, file_path: str, fallback_notice: str = "") -> str:
    """Render the short user-facing reply."""
    if not getattr(report, "review_passed", True):
        issues = getattr(report, "review_issues", []) or []
        caveat = ("质检未完全通过：" + "；".join(str(item) for item in issues[:2]))[:120]
    elif report.limitations:
        caveat = report.limitations[0][:120]
    elif report.confidence == "低":
        caveat = "来源质量或交叉验证不足，建议继续追踪官方来源。"
    else:
        caveat = "已按事件聚类和证据链生成报告。"

    return USER_REPLY_TEMPLATE.format(
        one_line_conclusion=report.one_line_conclusion or "见报告详情",
        confidence=report.confidence,
        event_count=len(report.events),
        top_count=len(report.top_events),
        source_count=report.source_count,
        read_success_count=report.read_success_count,
        main_caveat=caveat,
        file_path=file_path,
        fallback_notice=f"\n{fallback_notice}" if fallback_notice else "",
    )
