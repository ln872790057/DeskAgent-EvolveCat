"""ConflictResolver — detect and resolve conflicting behavioral rules."""
from datetime import date

CONFLICT_KEYWORD_PAIRS = [
    ({"简洁", "简短", "短", "少"}, {"详细", "长", "多", "全面", "完整"}),
    ({"主动", "搭话", "打招呼"}, {"被动", "不主动", "等"}),
    ({"毒舌", "犀利", "刻薄"}, {"温和", "客气", "礼貌"}),
    ({"代码优先", "先代码"}, {"思路优先", "先思路", "先分析"}),
]


def detect_conflict(rule1: dict, rule2: dict) -> bool:
    """Check if two rules contain opposing keywords."""
    c1 = set(rule1.get("content", ""))
    c2 = set(rule2.get("content", ""))
    for set_a, set_b in CONFLICT_KEYWORD_PAIRS:
        if (c1 & set_a and c2 & set_b) or (c1 & set_b and c2 & set_a):
            return True
    return False


def resolve(rule1: dict, rule2: dict, scene_tags: list[str]) -> dict:
    """Resolve a conflict between two rules.

    Returns: {
        "resolved": bool,
        "winner": rule_dict or None,
        "reason": str,
        "needs_user_input": bool,
    }
    """
    from agent.memory.self_evolution.rule_manager import RuleManager
    mgr = RuleManager()
    s1 = mgr.compute_match_score(scene_tags, rule1.get("scope_tags", []))
    s2 = mgr.compute_match_score(scene_tags, rule2.get("scope_tags", []))

    # Rule: score diff > 0.3 → use higher match
    if abs(s1 - s2) > 0.3:
        winner = rule1 if s1 > s2 else rule2
        return {"resolved": True, "winner": winner, "reason": f"匹配分 {max(s1,s2):.2f} > {min(s1,s2):.2f}", "needs_user_input": False}

    # Rule: newer wins if close scores
    d1 = date.fromisoformat(rule1.get("created_at", "2025-01-01"))
    d2 = date.fromisoformat(rule2.get("created_at", "2025-01-01"))
    if abs(s1 - s2) <= 0.3 and abs((d1 - d2).days) >= 1:
        winner = rule1 if d1 > d2 else rule2
        return {"resolved": True, "winner": winner, "reason": f"更新({max(d1,d2).isoformat()})", "needs_user_input": False}

    # Rule: higher weight wins
    w1 = rule1.get("weight", 0.1)
    w2 = rule2.get("weight", 0.1)
    if abs(w1 - w2) >= 0.1:
        winner = rule1 if w1 > w2 else rule2
        return {"resolved": True, "winner": winner, "reason": f"权重 {max(w1,w2):.2f} > {min(w1,w2):.2f}", "needs_user_input": False}

    # Still ambiguous → needs user input
    return {"resolved": False, "winner": None, "reason": "匹配分/时间/权重都接近", "needs_user_input": True}


def check_active_rules_conflicts(rules: list[dict]) -> list[tuple]:
    """Scan all active rules and return conflicting pairs."""
    conflicts = []
    for i in range(len(rules)):
        for j in range(i + 1, len(rules)):
            if detect_conflict(rules[i], rules[j]):
                conflicts.append((rules[i], rules[j]))
    return conflicts
