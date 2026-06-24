# agent/runtime/auto_checkpoint.py
"""Auto-checkpoint: snapshot session state at configurable intervals.

v3.3: Protects long-running tasks with automatic snapshots.
- Per-N-turns snapshot (default every 5 turns)
- Pre-risky-operation snapshot (high risk_level tools)
- Configurable via env vars and session metadata.
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
CHECKPOINT_PRE_RISK_LEVELS = {"high"}  # risk levels that trigger pre-op snapshot
CHECKPOINT_ENABLED = os.environ.get("AUTO_CHECKPOINT_ENABLED", "1") != "0"


def _session_checkpoint_dir(session_id: str, workspace_id: str) -> Path:
    """Get the checkpoint directory for a session."""
    return Path("workspaces") / workspace_id / "sessions" / session_id / "checkpoints"


def should_auto_checkpoint(
    session: Any,
    turn_count: int,
    interval: int = CHECKPOINT_INTERVAL_TURNS,
) -> bool:
    """Determine if an automatic checkpoint should be created this turn."""
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
    """Check if a checkpoint should run before executing a risky tool."""
    if not CHECKPOINT_ENABLED:
        return False
    return risk_level in risky_levels


def create_auto_checkpoint(
    session: Any,
    reason: str = "auto",
    context: Optional[Any] = None,
) -> Optional[dict]:
    """Create an automatic session checkpoint.

    Returns checkpoint metadata dict or None on failure.
    """
    try:
        sid = getattr(session, "session_id", "") or ""
        wsid = getattr(session, "workspace_id", "default") or "default"
        if not sid:
            return None

        # Gather session messages for the snapshot
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
        }

        # Persist as JSON
        ckpt_dir = _session_checkpoint_dir(sid, wsid)
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = ckpt_dir / f"{ckpt['checkpoint_id']}.json"
        ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2))

        # Attach to session metadata for easy reference
        if hasattr(session, "metadata") and isinstance(session.metadata, dict):
            ckpts = session.metadata.get("auto_checkpoints", [])
            ckpts.append(ckpt["checkpoint_id"])
            session.metadata["auto_checkpoints"] = ckpts[-20:]  # keep last 20

        _log.info(
            "Auto-checkpoint %s created for session %s (turn %s, %s msgs, reason=%s)",
            ckpt["checkpoint_id"], sid, ckpt["turn"], message_count, reason,
        )
        return ckpt
    except Exception as e:
        _log.warning("Failed to create auto-checkpoint for session %s: %s",
                     getattr(session, "session_id", ""), e)
        return None


def list_auto_checkpoints(session: Any) -> list[dict]:
    """List auto-checkpoints for a session."""
    try:
        sid = getattr(session, "session_id", "") or ""
        wsid = getattr(session, "workspace_id", "default") or "default"
        if not sid:
            return []
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
    """Run auto-checkpoint logic for the current turn/step.

    Called by the runner before each LLM step and before tool execution.
    Returns checkpoint metadata if one was created.
    """
    if not CHECKPOINT_ENABLED:
        return None

    turn_count = getattr(session, "turn_count", None)
    if turn_count is None and hasattr(session, "metadata"):
        turn_count = (session.metadata or {}).get("turn_count", 0)

    if should_auto_checkpoint(session, turn_count or 0):
        return create_auto_checkpoint(session, reason=f"turn_{turn_count}")

    return None
