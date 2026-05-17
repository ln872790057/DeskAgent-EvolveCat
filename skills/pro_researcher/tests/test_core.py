"""Quick unit tests for core research logic — run directly with python."""
import sys, os, json, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from skills.pro_researcher.query_planner import generate_search_queries, get_budget, is_ai_daily_topic, detect_research_type, score_research_types
from skills.pro_researcher.filters import (
    deduplicate_sources, classify_source_type, grade_source_quality,
    is_clickbait, is_pr_content, normalize_url, mark_source_quality,
    is_low_value_source,
)
from skills.pro_researcher.models import ResearchSource
from skills.pro_researcher.researcher import _parse_json_object, _events_from_analysis, _append_source_card_candidates
from agent.runtime.task_session import TaskSession
from agent.router.intent_router import route_intent
from skills.pro_researcher.planner import create_research_plan
from skills.pro_researcher.critic import review_report
from skills.pro_researcher.models import ResearchReport, ResearchEvent

def test_queries():
    qs = generate_search_queries("MCP协议", depth=3)
    budget = get_budget(3)
    assert len(qs) <= budget["query_count"], f"Expected <= {budget['query_count']}, got {len(qs)}"
    assert any("2026" in q or "2025" in q for q in qs), "Should include current year"
    assert len(qs) >= 5, f"depth=3 should have >=5 queries, got {len(qs)}"
    print(f"PASS: query_planner — {len(qs)} queries for depth=3")

def test_ai_daily_queries():
    qs = generate_search_queries("近期AI新闻", depth=3)
    assert is_ai_daily_topic("近期AI新闻")
    assert any("site:openai.com" in q or "site:anthropic.com" in q for q in qs), "AI daily mode should include official sources"
    assert any("Agent" in q or "智能体" in q for q in qs), "AI daily mode should cover Agent"
    assert len(qs) <= get_budget(3)["query_count"]
    print(f"PASS: AI daily query planner — {len(qs)} queries")

def test_dedup():
    s1 = ResearchSource(title="A", url="https://example.com/page?x=1")
    s2 = ResearchSource(title="A copy", url="https://example.com/page/")
    result = deduplicate_sources([s1, s2])
    assert len(result) == 1, f"Expected 1 after dedup, got {len(result)}"
    print("PASS: deduplication")

def test_classify():
    assert classify_source_type("", "https://github.com/x/repo") == "github"
    assert classify_source_type("战略合作 赋能 签约", "https://prnewswire.com/pr") == "pr"
    assert classify_source_type("Research paper on AI", "https://arxiv.org/abs/1234") in ("paper", "official")  # both fine
    assert classify_source_type("", "https://zhihu.com/question/123") == "self_media"
    assert classify_source_type("AI news daily", "https://blog.csdn.net/example") == "self_media"
    assert classify_source_type("OpenAI announces model", "https://openai.com/index/model") == "official"
    print("PASS: source classification")

def test_clickbait():
    assert is_clickbait("惊呆了！MCP彻底爆了")
    assert not is_clickbait("MCP Protocol Specification v1.0")
    print("PASS: clickbait detection")

def test_pr():
    assert is_pr_content("某公司隆重发布战略合作，赋能行业发展，引领生态共赢")
    assert not is_pr_content("MCP is a protocol for model context")
    print("PASS: PR detection")

def test_normalize():
    u1 = normalize_url("https://example.com/page/?x=1#section")
    u2 = normalize_url("https://example.com/page#other")
    assert u1 == u2, f"URLs should normalize to same: {u1} vs {u2}"
    print("PASS: URL normalization")

def test_budget():
    b1 = get_budget(1)
    b3 = get_budget(3)
    b5 = get_budget(5)
    assert b1["query_count"] == 5
    assert b3["query_count"] == 12
    assert b5["query_count"] == 22
    assert b3["batch_size"] >= 5
    print("PASS: depth budgets")

def test_quality_grading():
    s1 = ResearchSource(title="", url="https://docs.example.com", source_type="official", read_status="full")
    s2 = ResearchSource(title="战略合作", url="https://prnewswire.com/pr", source_type="pr", read_status="snippet_only")
    s3 = ResearchSource(title="震惊", url="https://clickbait.example.com", source_type="unknown", read_status="snippet_only")
    assert grade_source_quality(s1) == "S"
    assert grade_source_quality(s2) == "C"
    assert grade_source_quality(s3) == "C"
    print("PASS: source quality grading")

def test_research_type_detection():
    assert detect_research_type("MCP protocol technical architecture") == "technical"
    assert detect_research_type("Cursor vs Claude Code pricing features") == "product"
    assert detect_research_type("EU AI Act regulation impact") == "policy"
    assert detect_research_type("xAI shutdown rumor true or false") == "controversy"
    assert detect_research_type("洁柔纸巾公司（中顺洁柔）深度调研", ["产品线与品牌矩阵", "财务表现与经营数据", "供应链与生产基地"]) == "company"
    scores = score_research_types("洁柔纸巾公司（中顺洁柔）深度调研", ["产品线", "财报", "供应链"])
    assert scores["company"] > scores["product"]
    print("PASS: research type detection")

def test_company_query_planning():
    qs = generate_search_queries("中顺洁柔 公司深度调研", depth=3, focus=["财务表现", "竞争格局"])
    joined = "\n".join(qs)
    assert "年报" in joined or "财报" in joined
    assert "cninfo.com.cn" in joined or "szse.cn" in joined or "sse.com.cn" in joined
    plan = create_research_plan("中顺洁柔 公司深度调研", depth=3, focus=["财务表现"])
    assert plan.research_type == "company"
    assert "年报" in " ".join(plan.preferred_sources)
    print("PASS: company query planning")

def test_core_source_gate():
    home = ResearchSource(title="Home \\ Anthropic", url="https://www.anthropic.com/", domain="anthropic.com", source_type="official", read_status="full", content="Research Company Developers News")
    news = ResearchSource(title="Introducing Claude Opus 4.6 - Anthropic", url="https://www.anthropic.com/news/claude-opus-4-6", domain="anthropic.com", source_type="official", read_status="full", content="Claude Opus 4.6 improves coding and agent workloads.")
    roundup = ResearchSource(title="AI新闻完整摘要与链接汇总-2026年5月8日原创", url="https://blog.csdn.net/example", domain="blog.csdn.net", source_type="self_media", read_status="full", content="multiple reposted news")
    translated = ResearchSource(title="2026斯坦福人工智能指数报告（万字中译版）-虎嗅网", url="https://m.huxiu.com/article/1.html", domain="m.huxiu.com", source_type="media", read_status="full", content="translated roundup")
    release_notes = ResearchSource(title="Model Release Notes | OpenAI Help Center", url="https://help.openai.com/en/articles/9624314-model-release-notes", domain="help.openai.com", source_type="official", read_status="full", content="release note listing")
    mark_source_quality(home)
    mark_source_quality(news)
    mark_source_quality(roundup)
    mark_source_quality(translated)
    mark_source_quality(release_notes)
    assert home.usable_for_core is False
    assert news.usable_for_core is True
    assert roundup.usable_for_core is False
    assert translated.usable_for_core is False
    assert release_notes.usable_for_core is False
    assert is_low_value_source(translated)
    events = _events_from_analysis([{"title": "Home \\ Anthropic", "summary": "navigation", "source_urls": [home.url]}, {"title": news.title, "summary": "specific release", "source_urls": [news.url]}], [home, news])
    assert len(events) == 1 and events[0].title == news.title
    print("PASS: core source gate")

def test_json_repair_parser():
    parsed = _parse_json_object('```json\n{"events":[{"title":"A","source_urls":["u"],}], "key_findings":["x",],}\n```')
    assert parsed.get("events")[0]["title"] == "A"
    parsed2 = _parse_json_object('[{"title":"B","source_urls":["u"]}]')
    assert parsed2.get("events")[0]["title"] == "B"
    print("PASS: JSON repair parser")

def test_source_card_recovery():
    source = ResearchSource(
        title="OpenAI releases a new model for agent workflows",
        url="https://openai.com/index/new-agent-model",
        domain="openai.com",
        source_type="official",
        quality="S",
        read_status="full",
        content="OpenAI released a new model for agent workflows with improved tool use and coding performance.",
    )
    mark_source_quality(source)
    events = []
    added = _append_source_card_candidates(events, [source], "最新AI新闻", "news", max_total=5)
    assert added == 1
    assert events[0]["source_urls"] == [source.url]
    assert _append_source_card_candidates(events, [source], "最新AI新闻", "news", max_total=5) == 0
    print("PASS: source card recovery")

def test_task_session_artifacts():
    session = TaskSession.create("artifact smoke", "research", "artifact smoke")
    store = session.artifacts
    store.write_json("sample.json", {"ok": True, "source": ResearchSource(title="A", url="https://example.com")})
    store.append_jsonl("sample.jsonl", {"row": 1})
    with store.stage("sample_stage"):
        store.write_text("sample.txt", "hello")
    assert (store.root / "sample.json").exists()
    assert (store.root / "sample.jsonl").exists()
    assert (store.root / "sample.txt").exists()
    assert (store.root / "timing.json").exists()
    shutil.rmtree(store.root, ignore_errors=True)
    print("PASS: task session artifacts")

def test_intent_router():
    assert route_intent("在吗").task_kind == "CHAT"
    assert route_intent("调研洁柔这家公司").workflow == "research"
    assert route_intent("帮我修复这个 bug").workflow == "coding"
    assert route_intent("分析这个 csv 数据").workflow == "data_analysis"
    assert route_intent("明天9点提醒我").workflow == "schedule"
    print("PASS: intent router")

def test_research_critic():
    good_source = ResearchSource(title="2025 年报", url="https://cninfo.com.cn/report", source_type="official", quality="S", read_status="full")
    events = [
        ResearchEvent(title="发布年报", summary="公司发布年报。", source_urls=[good_source.url], why_it_matters="财务表现影响投资者判断。"),
        ResearchEvent(title="披露战略", summary="公司披露战略。", source_urls=[good_source.url], why_it_matters="战略影响长期经营。"),
        ResearchEvent(title="说明风险", summary="公司说明风险。", source_urls=[good_source.url], why_it_matters="风险影响估值判断。"),
    ]
    report = ResearchReport(
        topic="公司调研",
        research_type="company",
        one_line_conclusion="公司经营改善但仍需关注竞争。",
        editorial_summary="这是一段足够长的编辑摘要，用于说明公司经营、财务、竞争和风险判断，避免报告只是来源列表。",
        sources=[good_source],
        events=events,
        top_events=events,
    )
    result = review_report(report)
    assert result.score >= 70
    weak = ResearchSource(title="百科", url="https://baike.baidu.com/item/x", source_type="aggregator", quality="C", read_status="snippet_only", usable_for_core=False)
    bad_report = ResearchReport(topic="公司调研", research_type="company", sources=[weak], events=[ResearchEvent(title="百科条目", summary="泛来源", source_urls=[weak.url])], top_events=[ResearchEvent(title="百科条目", summary="泛来源", source_urls=[weak.url])])
    bad = review_report(bad_report)
    assert not bad.passed
    assert any(issue.severity == "high" for issue in bad.issues)
    english_events = [
        ResearchEvent(
            title=f"OpenAI announces new model {i}",
            summary="这是一条足够长的中文摘要，用于说明核心事实、背景信息和可能影响，避免被短内容规则误伤。",
            source_urls=[good_source.url],
            why_it_matters="这是一段足够长的中文影响判断，用于说明相关企业、开发者和用户可能受到的影响。",
        )
        for i in range(5)
    ]
    english_report = ResearchReport(
        topic="AI news",
        research_type="news",
        one_line_conclusion="测试英文标题是否会被打回。",
        editorial_summary="这是一段足够长的中文编辑摘要，用于验证标题语言质检是否能拦截中英混合报告。",
        sources=[good_source],
        events=english_events,
        top_events=english_events,
    )
    english = review_report(english_report)
    assert not english.passed
    print("PASS: research critic")


if __name__ == "__main__":
    test_queries()
    test_ai_daily_queries()
    test_dedup()
    test_classify()
    test_clickbait()
    test_pr()
    test_normalize()
    test_budget()
    test_quality_grading()
    test_research_type_detection()
    test_company_query_planning()
    test_core_source_gate()
    test_json_repair_parser()
    test_source_card_recovery()
    test_task_session_artifacts()
    test_intent_router()
    test_research_critic()
    print("\n=== ALL TESTS PASSED ===")
