"""DreamWorker — data-driven memory maintenance during user idle time."""
import time as _time
from datetime import datetime, date

from PySide6.QtCore import QThread, Signal

from utils.logger import get_logger

logger = get_logger("agent.memory.dream")


class DreamWorker(QThread):
    """Performs memory maintenance (log distillation, MEMORY.md compression,
    SQLite cleanup) when the user is away and conditions are met."""

    dream_started = Signal()
    dream_finished = Signal()

    def __init__(self, memory_store, file_store, llm_client, agent, rule_manager=None, parent=None):
        super().__init__(parent)
        self.memory_store = memory_store
        self.file_store = file_store
        self._client = llm_client
        self._agent = agent
        self._rule_manager = rule_manager
        self._unprocessed_rounds = 0
        self._last_dream_time = 0.0
        self._dreamed_today = False
        self._running = False

    def on_chat_end(self):
        """Called by PetAgent after each conversation turn."""
        self._unprocessed_rounds += 1

    def on_user_leave(self):
        """Called when WindowMonitor detects user idle > 15 min."""
        self._check_and_dream()

    def on_user_return(self):
        """Called when user becomes active again."""
        pass

    # ── QThread ──

    def run(self):
        self._running = True
        # Periodic check every 5 minutes while thread is alive
        while self._running:
            self._check_and_dream()
            self.msleep(300000)  # 5 minutes

    def stop(self):
        self._running = False

    # ── Dream logic ──

    def _check_and_dream(self):
        if not self._should_dream():
            return
        self._dreamed_today = True
        self._last_dream_time = _time.time()
        self._unprocessed_rounds = 0

        logger.info("[Dream] starting dream cycle")
        self.dream_started.emit()

        try:
            # 1. Distill old logs (>30 days)
            deleted = self.file_store.distill_old_logs(self._client, days=30)
            if deleted:
                logger.info(f"[Dream] distilled {deleted} old logs")

            # 2. Compress MEMORY.md if > 6KB
            from agent.memory.file_store import read_memory_md, compress_memory_md
            md = read_memory_md()
            if len(md.encode("utf-8")) > 6144:
                compress_memory_md(self._client, 4096)

            # 3. Cleanup low-value SQLite memories
            removed = self.memory_store.cleanup(max_items=500)
            if removed:
                logger.info(f"[Dream] cleaned {removed} low-value memories")

            # 4. Sync recent log highlights to MEMORY.md
            self._sync_recent_logs()

            # 5. Evolution maintenance (rule cleanup + merge + pattern discovery)
            if self._rule_manager:
                self._evolve_maintenance()

            # 6. Weekly evolution report (Sunday)
            if datetime.now().weekday() == 6 and self._rule_manager:
                self._weekly_evolution_report()

        except Exception:
            logger.exception("[Dream] dream cycle failed")
        finally:
            self.dream_finished.emit()
            logger.info("[Dream] dream cycle complete")

    def _should_dream(self) -> bool:
        now = _time.time()

        # Cooldown: minimum 30 min between dreams
        if self._last_dream_time and now - self._last_dream_time < 1800:
            return False

        # A: user away 15 min + unprocessed rounds > 15
        # (checked via on_user_leave, which calls _check_and_dream)
        if self._unprocessed_rounds >= 15:
            return True

        # B: MEMORY.md > 6KB
        from agent.memory.file_store import read_memory_md
        md = read_memory_md()
        if len(md.encode("utf-8")) > 6144:
            return True

        # C: unprocessed logs > 3 days
        from agent.memory.file_store import get_unprocessed_logs
        pending = get_unprocessed_logs(days=3)
        if pending:
            return True

        # Fallback: haven't dreamed today + user is away
        if not self._dreamed_today and self._unprocessed_rounds > 0:
            return True

        return False

    def _evolve_maintenance(self):
        """Clean up outdated rules, merge similar ones."""
        mgr = self._rule_manager
        if not mgr:
            return
        active = mgr.get_active_rules()
        if not active:
            return

        now = datetime.now()
        for r in active:
            rid = r.get("rule_id", "")
            last = r.get("last_triggered", "")
            validations = r.get("validations", 0)
            failures = r.get("failures", 0)

            # Mark outdated: >30 days since last trigger
            if last:
                try:
                    days_since = (now - datetime.fromisoformat(last)).days
                    if days_since > 60 and validations < failures:
                        mgr.delete_rule(rid)
                        logger.info(f"[Dream] deprecated outdated rule: {rid}")
                    elif days_since > 30:
                        mgr.update_rule(rid, status="possibly_outdated")
                except ValueError:
                    pass

            # Check for dead rules: 3 consecutive failures
            if failures >= 3 and validations == 0:
                mgr.delete_rule(rid)
                logger.info(f"[Dream] removed failed rule: {rid}")

        # Merge very similar rules
        from agent.memory.self_evolution.conflict_resolver import detect_conflict
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                r1, r2 = active[i], active[j]
                if detect_conflict(r1, r2):
                    continue  # conflicts handled separately
                # Similar content + same tags → merge
                t1 = set(r1.get("scope_tags", []))
                t2 = set(r2.get("scope_tags", []))
                if t1 == t2 and len(set(r1.get("content", "")) & set(r2.get("content", ""))) / max(len(set(r1.get("content", "")) | set(r2.get("content", ""))), 1) > 0.5:
                    v1 = r1.get("validations", 0)
                    v2 = r2.get("validations", 0)
                    if v1 >= v2:
                        mgr.update_rule(r1["rule_id"], validations=v1 + v2)
                        mgr.delete_rule(r2["rule_id"])
                    else:
                        mgr.update_rule(r2["rule_id"], validations=v1 + v2)
                        mgr.delete_rule(r1["rule_id"])
                    logger.info(f"[Dream] merged similar rules: {r1['rule_id']} + {r2['rule_id']}")

    def _weekly_evolution_report(self):
        """Generate and display the weekly evolution report."""
        mgr = self._rule_manager
        if not mgr:
            return
        stats = mgr.get_all_stats()
        if stats["total_active"] == 0 and stats["total_promoted"] == 0:
            return

        from agent.memory.self_evolution.message_manager import MessageManager
        mm = MessageManager()
        pending = mm.get_pending()
        report = mm.build_weekly_report(stats, pending)
        mm.clear_pending()

        logger.info(f"[Dream] weekly evolution report: {stats}")
        # Show via pet bubble if pet is available
        if self._agent and hasattr(self._agent, '_dream_worker'):
            # The pet reference is available through the agent
            pass  # Will be connected via signal in main.py

    def _sync_recent_logs(self):
        """Extract highlights from recent (3-7 day) logs into MEMORY.md."""
        from agent.memory.file_store import list_daily_logs, read_daily_log, append_to_memory_md
        logs = list_daily_logs()
        recent = logs[-7:] if len(logs) > 7 else logs
        if not recent:
            return

        text = ""
        for d in recent[-3:]:  # last 3 days
            content = read_daily_log(d)
            if content:
                text += content[-500:]  # tail of each log

        if not text.strip():
            return

        prompt = (
            "从以下近期对话日志中提取值得长期记住的关键信息（偏好、事件、事实）。"
            "输出为一行一条的简洁文本。没有重要信息就输出'无'。\n\n" + text[-3000:]
        )
        try:
            result = self._client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
            )
            extracted = result.get("content", "").strip()
            if extracted and extracted != "无":
                append_to_memory_md(extracted)
        except Exception:
            logger.debug("[Dream] sync_recent_logs failed (non-critical)", exc_info=True)
