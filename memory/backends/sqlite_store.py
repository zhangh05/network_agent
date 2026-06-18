# memory/backends/sqlite_store.py
"""SQLite memory store backend with FTS5 full-text search.

Stores memory records in a SQLite database with FTS5 index for fast search.
Falls back to LIKE queries when FTS5 is not available (e.g. older Python builds).

Database path default: workspaces/<ws>/memory/memory.sqlite3
"""

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
WS_ROOT = ROOT / "workspaces"

# ── Table DDL ──

_MEMORIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    key TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    value_preview TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""

_MEMORIES_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)",
    "CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)",
]

_FTS_TABLE_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key,
    value_preview,
    value,
    content='memories',
    content_rowid='rowid'
)
"""

_FTS_TRIGGERS_DDL = [
    """
    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, key, value_preview, value)
        VALUES (new.rowid, new.key, new.value_preview, new.value);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, key, value_preview, value)
        VALUES ('delete', old.rowid, old.key, old.value_preview, old.value);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, key, value_preview, value)
        VALUES ('delete', old.rowid, old.key, old.value_preview, old.value);
        INSERT INTO memories_fts(rowid, key, value_preview, value)
        VALUES (new.rowid, new.key, new.value_preview, new.value);
    END
    """,
]


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class SQLiteMemoryStore:
    """SQLite-backed memory store with FTS5 full-text search.

    Features:
    - FTS5 search (fast full-text) with LIKE fallback
    - CRUD operations: add, get, update_status, list, search
    - Per-workspace isolation via workspace_id column
    - Session-scoped filtering support
    """

    def __init__(self, db_path: str = None):
        """Initialize the store.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to <workspaces_root>/memory/memory.sqlite3.
        """
        self.db_path = db_path or str(WS_ROOT / "memory" / "memory.sqlite3")
        self._ensure_db()

    # ── Internal helpers ──

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_db(self) -> None:
        """Create database directory and tables if they don't exist."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = self._get_conn()
        try:
            conn.execute(_MEMORIES_TABLE_DDL)
            for idx_sql in _MEMORIES_INDEX_DDL:
                conn.execute(idx_sql)

            self._fts_available = self._try_create_fts(conn)
            conn.commit()
        finally:
            conn.close()

    def _try_create_fts(self, conn: sqlite3.Connection) -> bool:
        """Try to create FTS5 table. Returns True if FTS5 is available."""
        try:
            conn.execute(_FTS_TABLE_DDL)
            for trigger_sql in _FTS_TRIGGERS_DDL:
                conn.execute(trigger_sql)
            return True
        except sqlite3.OperationalError:
            # FTS5 not available — will fall back to LIKE
            return False

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        if row is None:
            return {}
        return dict(row)

    # ── Public API ──

    def add_memory(self, record: dict) -> str:
        """Insert a memory record and return its memory_id.

        Args:
            record: dict with keys: workspace_id, session_id, key, value,
                    value_preview, status, source, created_at, updated_at

        Returns:
            memory_id string
        """
        memory_id = record.get("memory_id") or uuid.uuid4().hex[:16]
        now = _now_iso()

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO memories
                   (memory_id, workspace_id, session_id, key, value,
                    value_preview, status, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    record.get("workspace_id", "default"),
                    record.get("session_id", ""),
                    record.get("key", ""),
                    record.get("value", ""),
                    record.get("value_preview", record.get("value", "")[:200]),
                    record.get("status", "active"),
                    record.get("source", ""),
                    record.get("created_at", now),
                    record.get("updated_at", now),
                ),
            )
            conn.commit()
            return memory_id
        finally:
            conn.close()

    def update_status(self, memory_id: str, status: str) -> bool:
        """Update the status of a memory record.

        Args:
            memory_id: The memory record id.
            status: New status value.

        Returns:
            True if the record was updated, False if not found.
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE memory_id = ?",
                (status, _now_iso(), memory_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def search(self, query: str, workspace_id: str,
               session_id: str = None, limit: int = 10) -> list:
        """Search memories using FTS5 (or LIKE fallback).

        Args:
            query: Search query string.
            workspace_id: Limit search to this workspace.
            session_id: Optional session filter.
            limit: Max results to return.

        Returns:
            List of memory dicts sorted by relevance (FTS) or updated_at (LIKE).
        """
        conn = self._get_conn()
        try:
            if self._fts_available and query.strip():
                return self._fts_search(conn, query, workspace_id,
                                        session_id, limit)
            else:
                return self._like_search(conn, query, workspace_id,
                                         session_id, limit)
        finally:
            conn.close()

    def _fts_search(self, conn: sqlite3.Connection, query: str,
                    workspace_id: str, session_id: str = None,
                    limit: int = 10) -> list:
        """FTS5 search implementation."""
        params: list = [workspace_id, query, limit]
        extra_where = ""
        if session_id:
            extra_where = " AND m.session_id = ?"
            params.insert(1, session_id)

        rows = conn.execute(
            f"""SELECT m.* FROM memories m
                JOIN memories_fts fts ON m.rowid = fts.rowid
                WHERE m.workspace_id = ?{extra_where}
                  AND memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _like_search(self, conn: sqlite3.Connection, query: str,
                     workspace_id: str, session_id: str = None,
                     limit: int = 10) -> list:
        """LIKE-based search fallback."""
        like_pattern = f"%{query}%"
        params: list = [workspace_id, like_pattern, like_pattern, limit]
        extra_where = ""
        if session_id:
            extra_where = " AND session_id = ?"
            params.insert(1, session_id)

        rows = conn.execute(
            f"""SELECT * FROM memories
                WHERE workspace_id = ?{extra_where}
                  AND (key LIKE ? OR value_preview LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_memories(self, workspace_id: str, session_id: str = None,
                      status: str = None, limit: int = 50) -> list:
        """List memories with optional filters.

        Args:
            workspace_id: Required workspace filter.
            session_id: Optional session filter.
            status: Optional status filter.
            limit: Max results.

        Returns:
            List of memory dicts.
        """
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM memories WHERE workspace_id = ?"
            params: list = [workspace_id]

            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            if status:
                sql += " AND status = ?"
                params.append(status)

            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get(self, memory_id: str) -> dict:
        """Get a single memory record by ID.

        Args:
            memory_id: The memory record id.

        Returns:
            Memory dict or empty dict if not found.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else {}
        finally:
            conn.close()

    def count(self, workspace_id: str = None) -> int:
        """Count memory records, optionally filtered by workspace."""
        conn = self._get_conn()
        try:
            if workspace_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories",
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
