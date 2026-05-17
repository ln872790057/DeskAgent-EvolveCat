"""MessageManager — rate limiting + special message generation."""
import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("agent.self_evolution.message_manager")

_STATS_PATH = Path(__file__).resolve().parent / "evolve_stats.json"


class MessageManager:
    """Controls how often special messages appear and generates their text."""

    PRIORITY_CORRECTION = 1   # user explicitly corrected
    PRIORITY_CONFLICT = 2     # rule conflict needs resolution
    PRIORITY_PATTERN = 3      # repeated task pattern
    PRIORITY_WEEKLY = 4       # deferred to weekly report

    def __init__(self):
        self._stats = self._load_stats()
        self._pending: list[dict] = []  # low-priority items deferred to weekly report

    def _load_stats(self) -> dict:
        defaults = {
            "daily_count": 0, "weekly_count": 0,
            "daily_reset": "", "weekly_reset": "",
            "last_sent": None, "normal_msg_since": 0,
            "total_rules_learned": 0, "total_promotions": 0,
            "total_corrections": 0, "validation_rate": 0.0,
        }
        if not _STATS_PATH.exists():
            return defaults
        try:
            with open(_STATS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in defaults.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return defaults

    def _save_stats(self):
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(_STATS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[MsgMgr] save stats failed: {e}")

    def _reset_daily(self):
        today = date.today().isoformat()
        if self._stats.get("daily_reset") != today:
            self._stats["daily_count"] = 0
            self._stats["daily_reset"] = today

    def _reset_weekly(self):
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        if self._stats.get("weekly_reset") != week_start:
            self._stats["weekly_count"] = 0
            self._stats["weekly_reset"] = week_start

    def can_send(self, priority: int = PRIORITY_PATTERN) -> bool:
        """Check if a special message can be sent now."""
        self._reset_daily()
        self._reset_weekly()

        if self._stats["daily_count"] >= 2:
            return False
        if self._stats["weekly_count"] >= 5:
            return False
        if self._stats["normal_msg_since"] < 5:
            # Allow priority 1 (correction) and 2 (conflict) even with low interval
            if priority > self.PRIORITY_CONFLICT:
                return False
        return True

    def record_sent(self):
        """Record that a special message was sent."""
        self._stats["daily_count"] += 1
        self._stats["weekly_count"] += 1
        self._stats["last_sent"] = datetime.now().isoformat()
        self._stats["normal_msg_since"] = 0
        self._save_stats()

    def record_normal_msg(self):
        self._stats["normal_msg_since"] = self._stats.get("normal_msg_since", 0) + 1
        self._save_stats()

    def add_pending(self, item: dict):
        """Add a low-priority item to the deferred list for weekly report."""
        self._pending.append(item)

    def get_pending(self) -> list[dict]:
        return self._pending

    def clear_pending(self):
        self._pending = []

    # ── Message builders ──

    def build_confirm_msg(self, rule_content: str, tags: list[str]) -> str:
        tag_str = " ".join(tags[:3])
        return (
            f"学了一招，要不要记住？\n\n"
            f"【规则】{rule_content}\n"
            f"【场景】{tag_str}\n\n"
            f"记住就按/记住，改场景就说/不对+场景名"
        )

    def build_conflict_msg(self, rules: list[dict], scene_tags: list[str]) -> str:
        tag_str = " ".join(scene_tags)
        lines = [f"脑子打架了，帮我选一下？\n当前场景：{tag_str}\n"]
        for i, r in enumerate(rules, 1):
            days_ago = "最近"
            try:
                created = r.get("created_at", "")
                if created:
                    delta = (date.today() - date.fromisoformat(created)).days
                    days_ago = f"{delta}天前"
            except Exception:
                pass
            lines.append(f"{i}. {r.get('content','?')}（{days_ago}学的，验证{r.get('validations',0)}次）")
        lines.append(f"\n选1 选2 / 看情况：xxx时候用1，yyy时候用2")
        return "\n".join(lines)

    def build_promotion_msg(self, rule_content: str) -> str:
        return f'"{rule_content}"这件事我记牢了，以后不会忘了。\n从learned-rules升到核心记忆了'

    def build_weekly_report(self, stats: dict, pending: list[dict]) -> str:
        lines = ["这周记了几条新东西\n"]
        lines.append("【新学会的】")
        for r in stats.get("new_rules", []):
            tags = " ".join(r.get("scope_tags", [])[:2])
            lines.append(f"  {r.get('content','?')} {tags}")

        promoted = stats.get("promoted_rules", [])
        if promoted:
            lines.append("\n【记牢的】")
            for r in promoted:
                lines.append(f"  {r.get('content','?')} 升到核心记忆")

        if pending:
            lines.append("\n【待确认】")
            for p in pending:
                lines.append(f"  {p.get('content','?')}")

        score = stats.get("confidence_score", 0)
        lines.append(f"\n【进化分】{score}分")
        return "\n".join(lines)
