"""SessionMessageStore — canonical chat-message persistence for a session.

v1.0.3.1: independent full-message storage.

v1.0.4 introduced the store as the single source of truth, but it still
derived content from `run.user_input_summary` (120-char) and
`run.final_response_summary` (300-char). Those are fine for run-record
metadata but too short for chat history.

v1.0.3.1 stores COMPLETE user/assistant messages independently:
  - `workspaces/<ws>/sessions/<sid>/messages/<run_id>:user.json`
  - `workspaces/<ws>/sessions/<sid>/messages/<run_id>:assistant.json`
  - Content is redaction-safe (no keys, no full configs).
  - Content > ARTIFACT_THRESHOLD (50 KB) is written as an artifact
    instead, and the message carries an `artifact_ref`.

The AgentSession in-memory list is now a *derived* cache, not the source.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.redaction import redact_text
from workspace.ids import validate_workspace_id, validate_session_id
from workspace.manager import ensure_workspace

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"

# Content > this value is stored as an artifact, not inline.
ARTIFACT_THRESHOLD = 50_000  # 50 KB

# Stable message_id shape. Pinned so the frontend dedup contract is
# invariant across reads.
USER_MSG_ID = "{run_id}:user"
ASSISTANT_MSG_ID = "{run_id}:assistant"


def _safe_run_id(run_id: str) -> str:
    """Return a run_id with only path-safe chars; raises if empty."""
    safe = re.sub(r'[^a-zA-Z0-9_:.-]', '', str(run_id))
    if safe != str(run_id) or not safe:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return safe


def _safe_rid(run_id: str) -> str:
    """Return a run_id stripped to path-safe chars."""
    return re.sub(r'[^a-zA-Z0-9_:.-]', '', str(run_id))


class SessionMessageStore:
    """Canonical chat-history read/write API for a single session.

    Stateless; constructed per-call. The constructor validates
    `ws_id` and `session_id` to prevent path traversal.
    """

    def __init__(self, session_id: str, ws_id: str = "default"):
        self.ws_id = validate_workspace_id(ws_id)
        self.session_id = validate_session_id(session_id)
        ensure_workspace(self.ws_id)

    # ── Paths ──

    def _session_path(self) -> Path:
        safe = _safe_run_id(self.session_id)
        return WS_ROOT / self.ws_id / "sessions" / f"{safe}.json"

    def _messages_dir(self) -> Path:
        """Directory holding independent full-message files."""
        safe = _safe_run_id(self.session_id)
        return WS_ROOT / self.ws_id / "sessions" / safe / "messages"

    def _msg_path(self, run_id: str, role: str) -> Path:
        """File path for a single full message."""
        rid = _safe_rid(run_id)
        return self._messages_dir() / f"{rid}:{role}.json"

    # ── Write ──

    def write_message(self, run_id: str, role: str, content: str,
                      metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Persist a FULL user or assistant message independently.

        Returns the message_id, or None if the content is empty.

        Content is redacted (no keys, no configs) before writing.
        If content exceeds ARTIFACT_THRESHOLD, it is saved as a temp
        artifact and the message stores an `artifact_ref` instead.
        """
        if not content or not content.strip():
            return None
        if role == "assistant":
            content = _sanitize_assistant_content(content)
            if not content or not content.strip():
                return None

        rid = _safe_rid(run_id)
        safe_content = redact_text(content) if len(content.encode("utf-8")) < ARTIFACT_THRESHOLD else content

        msg_dir = self._messages_dir()
        msg_dir.mkdir(parents=True, exist_ok=True)

        meta = dict(metadata or {})
        meta.setdefault("run_id", rid)
        meta.setdefault("session_id", self.session_id)
        meta.setdefault("workspace_id", self.ws_id)

        # Large content → artifact reference
        if len(content.encode("utf-8", errors="replace")) > ARTIFACT_THRESHOLD:
            artifact_id = self._write_artifact(content, role, rid)
            size = len(content.encode("utf-8", errors="replace"))
            record = {
                "role": role,
                "run_id": rid,
                "session_id": self.session_id,
                "content": "",
                "artifact_ref": {
                    "artifact_id": artifact_id,
                    "size_bytes": size,
                },
                "metadata": meta,
            }
        else:
            record = {
                "role": role,
                "run_id": rid,
                "session_id": self.session_id,
                "content": safe_content,
                "metadata": meta,
            }

        msg_path = self._msg_path(rid, role)
        _atomic_write(msg_path, record)

        msg_id = f"{rid}:{role}"
        return msg_id

    # ── Read ──

    def exists(self) -> bool:
        """True if the session record exists on disk."""
        path = self._session_path()
        return path.is_file()

    def get_messages(self) -> List[Dict[str, Any]]:
        """Return the full chat-history projection of the session.

        The `messages/` directory is the only source of truth.
        """
        return self._read_full_messages()

    def get_history_window(self, k: int = 8) -> List[Dict[str, Any]]:
        """Return up to k most recent messages (LLM context window).

        Messages are in chronological order (oldest first).
        """
        all_msgs = self.get_messages()
        if k <= 0 or len(all_msgs) <= k:
            return all_msgs
        return all_msgs[-k:]

    def get_message_count(self) -> int:
        return len(self.get_messages())

    # ── Full-message internals ──

    def _read_full_messages(self) -> List[Dict[str, Any]]:
        """Read messages from the `messages/` directory.

        Returns empty list if no full-message files exist.
        """
        msg_dir = self._messages_dir()
        if not msg_dir.is_dir():
            return []

        msgs: List[Dict[str, Any]] = []
        for f in sorted(msg_dir.glob("*.json")):
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
                role = record.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                msg_id = f.stem  # e.g. "run_001:user"

                m: Dict[str, Any] = {
                    "message_id": msg_id,
                    "session_id": record.get("session_id", self.session_id),
                    "role": role,
                    "content": _message_content(role, record.get("content", "")),
                    "created_at": record.get("metadata", {}).get("created_at", ""),
                    "run_id": record.get("run_id", ""),
                }

                # Carry artifact_ref if present (large content)
                if record.get("artifact_ref"):
                    art = record["artifact_ref"]
                    m["artifact_ref"] = art
                    m["content"] = (
                        f"[内容过大 ({art.get('size_bytes', 0) // 1024} KB)，"
                        f"请通过制品 API 获取: artifact_id={art.get('artifact_id', '')}]"
                    )

                # Carry metadata for frontend rendering
                meta = record.get("metadata", {})
                if meta:
                    m["metadata"] = {
                        k: meta[k] for k in ("run_id", "intent", "status",
                                              "capability", "quality_summary",
                                              "manual_review_count", "trace_id",
                                              "llm_metadata")
                        if k in meta
                    }

                msgs.append(m)
            except Exception:
                continue

        msgs.sort(key=_message_sort_key)
        return msgs

    # ── Artifact storage for large content ──

    def _write_artifact(self, content: str, role: str, run_id: str) -> str:
        """Write content > ARTIFACT_THRESHOLD as an artifact file.

        Returns the artifact_id.
        """
        artifact_id = f"msg_{_safe_rid(run_id)}_{role}_{uuid.uuid4().hex[:8]}"
        art_dir = WS_ROOT / self.ws_id / "files" / "agent"
        art_dir.mkdir(parents=True, exist_ok=True)
        art_path = art_dir / f"{artifact_id}.txt"
        art_path.write_text(content, encoding="utf-8")
        return artifact_id


def _message_sort_key(message: Dict[str, Any]) -> tuple:
    """Stable chronological chat ordering with user before assistant per run."""
    role_rank = 0 if message.get("role") == "user" else 1
    return (
        message.get("created_at") or "",
        message.get("run_id") or "",
        role_rank,
        message.get("message_id") or "",
    )


def _message_content(role: str, content: str) -> str:
    if role == "assistant":
        return _sanitize_assistant_content(content)
    return content


def _sanitize_assistant_content(content: str) -> str:
    """Strip provider reasoning from assistant text before display/context use."""
    if not content:
        return ""
    try:
        from agent.llm.runtime import sanitize_provider_output
        cleaned, _ = sanitize_provider_output(str(content))
        return cleaned
    except Exception:
        return str(content)


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp → rename."""
    import logging
    _log = logging.getLogger(__name__)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(path)
    except Exception as e:
        _log.warning("_atomic_write failed: %s", e)


def get_message_store(session_id: str = None, ws_id: str = "default") -> "SessionMessageStore":
    """Convenience factory for callers that need a SessionMessageStore instance."""
    return SessionMessageStore(session_id=session_id, ws_id=ws_id)
