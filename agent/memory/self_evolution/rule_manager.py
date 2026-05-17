"""RuleManager — CRUD + matching + tagging for self-evolution rules."""
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("agent.self_evolution.rule_manager")

_DIR = Path(__file__).resolve().parent
_RULES_PATH = _DIR / "rules_index.json"
_LEARNED_RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "memory" / "learned-rules.md"

# Keyword→tag mapping (order matters: more specific first)
KEYWORD_TAGS = {
    "📰 新闻查询": ["新闻", "最新", "热点", "资讯", "日报", "周报"],
    "🔍 搜索": ["搜索", "搜", "查一下", "找找", "查询"],
    "💻 写代码": ["代码", "编程", "实现", "函数", "写个", "程序"],
    "📝 写文档": ["文档", "文章", "报告", "总结", "写", "撰写"],
    "📊 分析": ["分析", "对比", "评估", "数据", "统计"],
    "🔧 调试": ["bug", "报错", "调试", "修", "错误", "fix"],
    "💬 闲聊": ["哈哈", "你好", "谢谢", "嗯", "哦", "好的", "晚安", "早安", "辛苦"],
    "🤔 提问": ["为什么", "怎么", "能不能", "可以", "如何", "是什么"],
    "✏️ 创建/修改": ["创建", "修改", "改", "换成", "调整", "更新", "重命名"],
}

APPROXIMATE_MATCHES = {
    ("📰 新闻查询", "🔍 搜索"): True,
    ("💻 写代码", "🔧 调试"): True,
    ("📝 写文档", "📊 分析"): True,
}
for (a, b) in list(APPROXIMATE_MATCHES.keys()):
    APPROXIMATE_MATCHES[(b, a)] = True


class RuleManager:
    """Manages learned behavioral rules with JSON persistence."""

    def __init__(self):
        self._rules: dict[str, dict] = {}
        self._dirty = False
        self._load()

    # ── Persistence ──

    def _load(self):
        if not _RULES_PATH.exists():
            return
        try:
            with open(_RULES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                rid = item.get("rule_id", "")
                if rid:
                    self._rules[rid] = item
            logger.info(f"[RuleMgr] loaded {len(self._rules)} rules")
        except Exception as e:
            logger.error(f"[RuleMgr] load failed: {e}")

    def _save(self):
        _RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = list(self._rules.values())
            with open(_RULES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._dirty = False
        except Exception as e:
            logger.error(f"[RuleMgr] save failed: {e}")

    # ── CRUD ──

    def add_rule(self, rule_dict: dict) -> str:
        rid = rule_dict.get("rule_id") or f"rule_{uuid.uuid4().hex[:6]}"
        rule_dict.setdefault("rule_id", rid)
        rule_dict.setdefault("status", "active")
        rule_dict.setdefault("weight", 0.1)
        rule_dict.setdefault("validations", 0)
        rule_dict.setdefault("failures", 0)
        rule_dict.setdefault("created_at", datetime.now().strftime("%Y-%m-%d"))
        rule_dict.setdefault("last_triggered", "")
        self._rules[rid] = rule_dict
        self._dirty = True
        self._save()
        self._sync_learned_rules()
        logger.info(f"[RuleMgr] added rule: {rid} content={rule_dict.get('content','')[:30]}")
        return rid

    def update_rule(self, rule_id: str, **kwargs):
        rule = self._rules.get(rule_id)
        if not rule:
            return
        for k, v in kwargs.items():
            if k in rule:
                rule[k] = v
        self._dirty = True
        self._save()
        if any(k in kwargs for k in ("content", "status", "validations")):
            self._sync_learned_rules()

    def delete_rule(self, rule_id: str):
        if rule_id in self._rules:
            self._rules[rule_id]["status"] = "deprecated"
            self._dirty = True
            self._save()
            self._sync_learned_rules()

    def get_rule(self, rule_id: str) -> dict | None:
        return self._rules.get(rule_id)

    def get_active_rules(self) -> list[dict]:
        return [r for r in self._rules.values() if r.get("status") == "active"]

    def get_rules_by_scope(self, scope_tags: list[str]) -> list[dict]:
        return [
            r for r in self.get_active_rules()
            if any(t in r.get("scope_tags", []) for t in scope_tags)
        ]

    # ── Tagging ──

    def tag_message(self, message: str) -> list[str]:
        """Tag a user message with scene labels. Keyword-only, no LLM."""
        tags = set()
        msg_lower = message.lower()
        for tag, keywords in KEYWORD_TAGS.items():
            for kw in keywords:
                if kw in msg_lower or kw.lower() in msg_lower:
                    tags.add(tag)
                    break
        # Always add at least one tag
        if not tags:
            tags.add("💬 闲聊")
        return sorted(tags)

    # ── Matching ──

    def compute_match_score(self, current_tags: list[str], rule_tags: list[str]) -> float:
        """Hard-rule matching score: task_type 0.4 + intent 0.3 + state 0.2 + time 0.1."""
        score = 0.0
        cur_set = set(current_tags)
        rule_set = set(rule_tags)

        for t in cur_set & rule_set:
            if t in {"📰 新闻查询", "🔍 搜索", "💻 写代码", "📝 写文档", "📊 分析", "🔧 调试"}:
                score += 0.4 / max(len(cur_set & rule_set), 1)
            elif t in {"💬 闲聊", "🤔 提问", "✏️ 创建/修改"}:
                score += 0.3 / max(len(cur_set & rule_set), 1)
            elif t in {"⚡ 忙碌", "😊 轻松", "🎯 专注"}:
                score += 0.2 / max(len(cur_set & rule_set), 1)

        # Approximate matches (task type only)
        task_types = {"📰 新闻查询", "🔍 搜索", "💻 写代码", "📝 写文档", "📊 分析", "🔧 调试"}
        cur_task = cur_set & task_types
        rule_task = rule_set & task_types
        for ct in cur_task:
            for rt in rule_task:
                if ct != rt and APPROXIMATE_MATCHES.get((ct, rt)):
                    score += 0.2
                    break

        return min(score, 1.0)

    def match_rules(self, current_tags: list[str], limit: int = 3) -> list[dict]:
        """Return top-N matching active rules for the given scene."""
        active = self.get_active_rules()
        scored = []
        for r in active:
            s = self.compute_match_score(current_tags, r.get("scope_tags", []))
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    # ── Similarity ──

    def find_similar(self, content: str, tags: list[str]) -> dict | None:
        """Quick filter: Jaccard on keywords + tag overlap. Returns candidate rule if similar."""
        content_words = set(content)
        for r in self.get_active_rules():
            r_tags = set(r.get("scope_tags", []))
            tag_overlap = len(set(tags) & r_tags) / max(len(set(tags) | r_tags), 1)
            r_words = set(r.get("content", ""))
            if r_words:
                jaccard = len(content_words & r_words) / max(len(content_words | r_words), 1)
            else:
                jaccard = 0
            if jaccard > 0.6 and tag_overlap > 0.3:
                return r
        return None

    # ── Validation / Promotion ──

    def increment_validation(self, rule_id: str):
        r = self._rules.get(rule_id)
        if r:
            r["validations"] = r.get("validations", 0) + 1
            r["last_triggered"] = datetime.now().strftime("%Y-%m-%d")
            self._dirty = True
            self._save()

    def increment_failure(self, rule_id: str):
        r = self._rules.get(rule_id)
        if r:
            r["failures"] = r.get("failures", 0) + 1
            self._dirty = True
            self._save()

    def check_promotion(self, rule_id: str) -> bool:
        r = self._rules.get(rule_id)
        if not r or r.get("status") != "active":
            return False
        v = r.get("validations", 0)
        f = r.get("failures", 0)
        if v < 10:
            return False
        return (f / max(v, 1)) < 0.2

    def promote_rule(self, rule_id: str) -> bool:
        """Promote rule to core memory (MEMORY.md)."""
        r = self._rules.get(rule_id)
        if not r:
            return False
        content = r.get("content", "")
        if not content:
            return False

        from agent.memory import file_store
        md = file_store.read_memory_md()
        line = f"- [rule:{r.get('type','')}] {content}"
        new_md = md + "\n" + line

        if len(new_md.encode("utf-8")) > file_store.MAX_MEMORY_SIZE:
            from agent.llm.router import LLMRouter
            client = LLMRouter().get_client()
            file_store.compress_memory_md(client, 4096)

        if not file_store.append_to_memory_md(line):
            # Fallback: try compression then append
            from agent.llm.router import LLMRouter
            client = LLMRouter().get_client()
            file_store.compress_memory_md(client, 4096)
            file_store.append_to_memory_md(line)

        r["status"] = "promoted"
        self._dirty = True
        self._save()
        self._sync_learned_rules()
        logger.info(f"[RuleMgr] promoted rule to core memory: {rule_id}")
        return True

    # ── learned-rules.md sync ──

    def _sync_learned_rules(self):
        """Write active rules to learned-rules.md."""
        active = self.get_active_rules()
        lines = ["# 习得规则\n"]
        if active:
            lines.append("## 活跃规则")
            for r in sorted(active, key=lambda x: x.get("validations", 0), reverse=True):
                tags = " ".join(r.get("scope_tags", []))
                v = r.get("validations", 0)
                lines.append(f"- [{r.get('type','')}] {r.get('content','')} {tags} ({v}次验证)")
        try:
            os.makedirs(_LEARNED_RULES_PATH.parent, exist_ok=True)
            with open(_LEARNED_RULES_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.error(f"[RuleMgr] sync learned-rules.md failed: {e}")

    def get_all_stats(self) -> dict:
        """Return aggregate stats for weekly report."""
        active = self.get_active_rules()
        promoted = [r for r in self._rules.values() if r.get("status") == "promoted"]
        total_v = sum(r.get("validations", 0) for r in active)
        total_f = sum(r.get("failures", 0) for r in active)
        return {
            "total_active": len(active),
            "total_promoted": len(promoted),
            "total_validations": total_v,
            "total_failures": total_f,
            "validation_rate": total_v / max(total_v + total_f, 1),
            "confidence_score": len(active) * 10 - total_f * 5 + int(total_v / max(total_v + total_f, 1) * 5),
        }
