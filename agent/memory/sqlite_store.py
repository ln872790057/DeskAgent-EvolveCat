"""SQLite memory store with keyword search, tags, and weighted scoring."""
import sqlite3
import os

from agent.memory.base import BaseMemoryStore, MemoryItem
from utils.logger import get_logger

logger = get_logger("agent.memory.sqlite")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "data", "memory.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_conn()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            access_count INTEGER DEFAULT 0
        )
    """)

    # Migration: add tags column if not exists
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN tags TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists

    conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC)")

    conn.commit()
    conn.close()


class SQLiteMemoryStore(BaseMemoryStore):
    def __init__(self):
        _init_db()

    def store(self, memory_type: str, content: str, importance: float,
              tags: str = "") -> int:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO memories (type, content, importance, tags) VALUES (?, ?, ?, ?)",
                (memory_type, content, importance, tags),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                """SELECT id, type, content, importance, created_at,
                          last_accessed, access_count, tags
                   FROM memories
                   WHERE content LIKE ? OR tags LIKE ?
                   ORDER BY (
                       importance * 0.4 +
                       (1.0 / (julianday('now') - julianday(created_at) + 1)) * 0.3 +
                       (CAST(access_count AS REAL) / 10.0) * 0.3
                   ) DESC
                   LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()

            # Update access
            ids = [r[0] for r in rows]
            if ids:
                conn.execute(
                    f"UPDATE memories SET last_accessed = CURRENT_TIMESTAMP, "
                    f"access_count = access_count + 1 WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
                conn.commit()

            return [MemoryItem(*r) for r in rows]
        finally:
            conn.close()

    def update_access(self, memory_id: int):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE memories SET last_accessed = CURRENT_TIMESTAMP, "
                "access_count = access_count + 1 WHERE id = ?",
                (memory_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def delete(self, memory_id: int) -> bool:
        conn = _get_conn()
        try:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def cleanup(self, max_items: int = 500) -> int:
        """Keep: importance>0.7, accessed in last 30 days, or top weighted. Delete rest."""
        conn = _get_conn()
        try:
            cur = conn.execute(
                """DELETE FROM memories WHERE id NOT IN (
                       SELECT id FROM memories WHERE
                           importance > 0.7
                           OR julianday('now') - julianday(last_accessed) < 30
                           OR id IN (
                               SELECT id FROM memories
                               ORDER BY (
                                   importance * 0.4 +
                                   (1.0 / (julianday('now') - julianday(created_at) + 1)) * 0.3 +
                                   (CAST(access_count AS REAL) / 10.0) * 0.3
                               ) DESC
                               LIMIT ?
                           )
                   )""",
                (max_items,),
            )
            conn.commit()
            deleted = cur.rowcount
            if deleted:
                logger.info(f"[SQLiteStore] cleanup: removed {deleted} low-value memories")
            return deleted
        finally:
            conn.close()

    def get_recent(self, limit: int = 10) -> list[MemoryItem]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                """SELECT id, type, content, importance, created_at,
                          last_accessed, access_count, tags
                   FROM memories ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [MemoryItem(*r) for r in rows]
        finally:
            conn.close()
