# agent/runtime/auto_checkpoint.py
"""Auto-checkpoint: snapshot session state at configurable intervals.

v3.3: Protects long-running tasks with automatic snapshots.
v3.8: SqliteSaver integration via LangGraph checkpoint, Postgres support.

- Per-N-turns snapshot (default every 5 turns)
- Pre-risky-operation snapshot (high risk_level tools)
- Configurable via env vars and session metadata.
- Sqlite checkpoint store replaces JSON file persistence.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────

CHECKPOINT_INTERVAL_TURNS = int(
    os.environ.get("AUTO_CHECKPOINT_INTERVAL_TURNS", "5")
)
CHECKPOINT_PRE_RISK_LEVELS = {"high"}
CHECKPOINT_ENABLED = os.environ.get("AUTO_CHECKPOINT_ENABLED", "1") != "0"
CHECKPOINT_BACKEND = os.environ.get("CHECKPOINT_BACKEND", "json")  # "json" | "sqlite" | "postgres"
CHECKPOINT_DB_PATH = os.environ.get("CHECKPOINT_DB_PATH", "workspaces/_runtime/checkpoints.db")
CHECKPOINT_PG_URL = os.environ.get("CHECKPOINT_PG_URL", "")


def _get_sqlite_saver():
    """Get or create SqliteSaver instance (lazy, cached)."""
    if not hasattr(_get_sqlite_saver, "_instance"):
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            _get_sqlite_saver._instance = SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH)
        except ImportError:
            _get_sqlite_saver._instance = None
    return _get_sqlite_saver._instance


def _get_postgres_saver():
    """Get or create PostgresSaver instance (lazy, cached)."""
    if not CHECKPOINT_PG_URL:
        return None
    if not hasattr(_get_postgres_saver, "_instance"):
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            _get_postgres_saver._instance = PostgresSaver.from_conn_string(CHECKPOINT_PG_URL)
        except ImportError:
            _get_postgres_saver._instance = None
    return _get_postgres_saver._instance


def _session_checkpoint_dir(session_id: str, workspace_id: str) -> Path:
    """Get the checkpoint directory for a session (JSON backend only)."""
    return Path("workspaces") / workspace_id / "sessions" / session_id / "checkpoints"


def should_auto_checkpoint(
    session: Any,
    turn_count: int,
    interval: int = CHECKPOINT_INTERVAL_TURNS,
) -> bool:
    if not CHECKPOINT_ENABLED:
        return False
    if interval <= 0:
        return False
    return turn_count > 0 and turn_count % interval == 0


def should_checkpoint_before_tool(
    tool_id: str,
    risk_level: str,
    risky_levels: set = CHECKPOINT_PRE_RISK_LEVELS,
) -> bool:
    if not CHECKPOINT_ENABLED:
        return False
    return risk_level in risky_levels


def create_auto_checkpoint(
    session: Any,
    reason: str = "auto",
    context: Optional[Any] = None,
) -> Optional[dict]:
    """Create an automatic session checkpoint.
    
    v3.8: Uses SqliteSaver/PostgresSaver when backend != "json".
    Falls back to JSON file persistence.
    """
    try:
        sid = getattr(session, "session_id", "") or ""
        wsid = getattr(session, "workspace_id", "default") or "default"
        if not sid:
            return None

        messages = getattr(session, "history", None) or getattr(session, "messages", None) or []
        message_count = len(messages) if isinstance(messages, list) else 0

        turn = getattr(session, "turn_count", None)
        if turn is None and hasattr(session, "metadata"):
            turn = session.metadata.get("turn_count", 0) if isinstance(session.metadata, dict) else 0

        ckpt = {
            "checkpoint_id": f"auto_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            "session_id": sid,
            "workspace_id": wsid,
            "message_count": message_count,
            "turn": turn or 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "backend": CHECKPOINT_BACKEND,
        }

        # v3.8: LangGraph checkpoint backends
        if CHECKPOINT_BACKEND == "sqlite":
            saver = _get_sqlite_saver()
            if saver:
                config = {"configurable": {"thread_id": sid}}
                saver.put(config, ckpt["checkpoint_id"], ckpt, {}, {})
                ckpt["_backend"] = "sqlite"
                _log.info("Sqlite checkpoint %s for session %s", ckpt["checkpoint_id"], sid)
        elif CHECKPOINT_BACKEND == "postgres":
            saver = _get_postgres_saver()
            if saver:
                config = {"configurable": {"thread_id": sid}}
                saver.put(config, ckpt["checkpoint_id"], ckpt, {}, {})
                ckpt["_backend"] = "postgres"
        else:
            # Legacy JSON file
            ckpt_dir = _session_checkpoint_dir(sid, wsid)
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            ckpt_path = ckpt_dir / f"{ckpt['checkpoint_id']}.json"
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2))

        if hasattr(session, "metadata") and isinstance(session.metadata, dict):
            ckpts = session.metadata.get("auto_checkpoints", [])
            ckpts.append(ckpt["checkpoint_id"])
            session.metadata["auto_checkpoints"] = ckpts[-20:]

        return ckpt
    except Exception as e:
        _log.warning("Failed to create auto-checkpoint: %s", e)
        return None


def list_auto_checkpoints(session: Any) -> list[dict]:
    """List auto-checkpoints for a session."""
    try:
        sid = getattr(session, "session_id", "") or ""
        wsid = getattr(session, "workspace_id", "default") or "default"
        if not sid:
            return []
        
        if CHECKPOINT_BACKEND == "sqlite":
            saver = _get_sqlite_saver()
            if saver:
                config = {"configurable": {"thread_id": sid}}
                try:
                    items = list(saver.list(config))
                    return [i.checkpoint for i in items if hasattr(i, 'checkpoint')]
                except Exception:
                    pass

        # Legacy JSON
        ckpt_dir = _session_checkpoint_dir(sid, wsid)
        if not ckpt_dir.exists():
            return []
        checkpoints = []
        for f in sorted(ckpt_dir.glob("auto_*.json")):
            try:
                ckpt = json.loads(f.read_text())
                ckpt["_file"] = str(f)
                checkpoints.append(ckpt)
            except (json.JSONDecodeError, OSError):
                pass
        return checkpoints
    except Exception:
        return []


def apply_checkpoint_guard(
    session: Any,
    turn: Any,
    step: int,
    context: Any = None,
) -> Optional[dict]:
    if not CHECKPOINT_ENABLED:
        return None

    turn_count = getattr(session, "turn_count", None)
    if turn_count is None and hasattr(session, "metadata"):
        turn_count = (session.metadata or {}).get("turn_count", 0)

    if should_auto_checkpoint(session, turn_count or 0):
        return create_auto_checkpoint(session, reason=f"turn_{turn_count}")

    return None


# ─── v3.8: Dynamic breakpoints ───

def get_dynamic_breakpoints() -> set[str]:
    """Get tool IDs to break before, from env var or session config.
    
    Usage: AGENT_BREAKPOINT_TOOLS="exec.run,git.commit,device.delete"
    """
    raw = os.environ.get("AGENT_BREAKPOINT_TOOLS", "")
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def should_break_before_tool(tool_id: str) -> bool:
    """Check if execution should pause before this tool (dynamic breakpoint)."""
    breakpoints = get_dynamic_breakpoints()
    return tool_id in breakpoints
