# workspace/memory_governance.py
"""Memory Governance — canonical schema, gate, retrieval, and conflict lifecycle."""

from __future__ import annotations
import json, time as _time, hashlib, logging, re, uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Literal
from workspace.run_store import WS_ROOT
from workspace.atomic_io import atomic_write_json
from agent.runtime.utils import from_iso, now_iso, to_iso

Scope = Literal["global","workspace","session","task"]
MemoryType = Literal[
    "user_preference","task_pattern","tool_learning","error_lesson",
    "artifact_summary","operational_fact","device_state","profile","knowledge_note",
]
MemoryStatus = Literal["pending","active","rejected","expired","conflict"]
MemorySource = Literal[
    "user","tool","file","manual_confirm","agent_suggestion","subagent",
    "llm_tool","task","action","user_signal",
]

_REDACT_KEYS = {"password","token","api_key","secret","credential","key","auth"}
_VALID_GATE_MODES = {"rule_only", "llm_first"}
_VALID_SCOPES = {"global", "workspace", "session", "task"}
_VALID_MEMORY_TYPES = {
    "user_preference", "task_pattern", "tool_learning", "error_lesson",
    "artifact_summary", "operational_fact", "device_state", "profile", "knowledge_note",
}
_MEMORY_ID_RE = re.compile(r"^mem-[a-f0-9]{12}$")

def _now(): return now_iso()
def _mid(): return f"mem-{uuid.uuid4().hex[:12]}"

@dataclass
class MemoryRecord:
    memory_id: str = field(default_factory=_mid)
    workspace_id: str = ""
    session_id: str = ""
    task_id: str = ""
    scope: Scope = "workspace"
    memory_type: MemoryType = "operational_fact"
    status: MemoryStatus = "pending"
    source: MemorySource = "agent_suggestion"
    source_ref: str = ""
    content: str = ""
    summary: str = ""
    confidence: float = 0.5
    ttl_seconds: Optional[int] = None
    expires_at: str = ""
    citations: list = field(default_factory=list)
    conflict_group: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""
    redacted: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        n = _now()
        if not self.created_at: self.created_at = n
        if not self.updated_at: self.updated_at = n
        if self.ttl_seconds and not self.expires_at:
            self.expires_at = to_iso(_time.time() + self.ttl_seconds)

    def is_retrievable(self) -> bool:
        if self.status != "active": return False
        if self.expires_at:
            try:
                if from_iso(self.expires_at) < _time.time():
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict): return cls(**{k:v for k,v in d.items() if k in cls.__dataclass_fields__})


class MemoryStore:
    """Persist memory records per workspace."""

    def __init__(self):
        pass

    def _validated_ws_id(self, ws_id: str) -> str:
        from workspace.ids import validate_workspace_id
        return validate_workspace_id(ws_id)

    def _dir(self, ws_id: str) -> Path:
        return WS_ROOT / self._validated_ws_id(ws_id) / "memory"

    def _path(self, ws_id: str, memory_id: str) -> Path:
        memory_id = str(memory_id or "")
        if not _MEMORY_ID_RE.fullmatch(memory_id):
            raise ValueError("invalid_memory_id")
        return self._dir(ws_id) / f"{memory_id}.json"

    def _save(self, record: MemoryRecord):
        """Internal write — gate checks are enforced by MemoryWriteGate."""
        record.workspace_id = self._validated_ws_id(record.workspace_id)
        record.content = _redact(record.content)
        record.summary = _redact(record.summary)
        record.source_ref = _redact(record.source_ref)
        try:
            from core.tools.redaction import redact_tool_output
            record.citations = redact_tool_output(list(record.citations or []))
            record.metadata = redact_tool_output(dict(record.metadata or {}))
        except Exception:
            record.citations = list(record.citations or [])
            record.metadata = dict(record.metadata or {})
        d = self._dir(record.workspace_id); d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path(record.workspace_id, record.memory_id), record.to_dict())

        # ContextStore is a retrievable projection, not the memory lifecycle
        # store. Only active, non-expired records may exist in this index.
        try:
            from core.context.context_store import get_context_store
            store = get_context_store(record.workspace_id)
            item_id = f"mh_{record.memory_id}"
            if record.is_retrievable():
                store.put({
                    "item_type": "memory_hit",
                    "item_id": item_id,
                    "workspace_id": record.workspace_id,
                    "source": "memory_governance",
                    "title": record.summary[:200] if record.summary else record.content[:200],
                    "summary": record.summary[:500] if record.summary else record.content[:500],
                    "content": record.content[:2000],
                    "memory_id": record.memory_id,
                    "memory_type": record.memory_type,
                    "confidence": record.confidence,
                    "scope": record.scope,
                    "session_id": record.session_id,
                    "task_id": record.task_id,
                    "expires_at": record.expires_at,
                    "tags": [],
                    "status": record.status,
                    "memory_status": record.status,
                    "confirmation_status": "confirmed",
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                })
            else:
                # Do not tombstone a projection that never existed. ContextStore
                # tombstones are terminal in list projections, so doing this for
                # a new pending record would prevent later confirmation from
                # making the same item retrievable.
                if store.get(item_id) is not None:
                    store.delete(item_id)
        except Exception as e:
            logging.getLogger("memory_governance._save").warning(
                "ContextStore index failed for memory %s: %s",
                record.memory_id, e,
            )

    def delete_file(self, ws_id: str, memory_id: str) -> bool:
        """Physically delete a memory record file."""
        ws_id = self._validated_ws_id(ws_id)
        record = self.get(ws_id, memory_id)
        try:
            p = self._path(ws_id, memory_id)
        except ValueError:
            return False
        if p.exists():
            p.unlink()
            try:
                from core.context.context_store import get_context_store
                context_store = get_context_store(ws_id)
                item_id = f"mh_{memory_id}"
                if context_store.get(item_id) is not None:
                    context_store.delete(item_id)
            except Exception as exc:
                logging.getLogger("memory_governance.delete").warning(
                    "ContextStore delete failed for memory %s: %s", memory_id, exc,
                )
            return True
        return False

    def get(self, ws_id: str, memory_id: str) -> Optional[MemoryRecord]:
        try:
            p = self._path(ws_id, memory_id)
        except ValueError:
            return None
        if not p.exists(): return None
        try: return MemoryRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception: return None

    def list_all(self, ws_id: str) -> list[MemoryRecord]:
        d = self._dir(ws_id)
        if not d.exists(): return []
        recs = []
        for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try: recs.append(MemoryRecord.from_dict(json.loads(f.read_text(encoding="utf-8"))))
            except Exception: continue
        return recs

    def list_by_status(self, ws_id: str, status: MemoryStatus) -> list[MemoryRecord]:
        return [r for r in self.list_all(ws_id) if r.status == status]

    def list_retrievable(self, ws_id: str, scope: Scope = "workspace",
                         session_id: str = "", memory_type: str = "",
                         limit: int = 100) -> list[dict]:
        all_recs = self.list_all(ws_id)
        results = []
        for r in all_recs:
            if not r.is_retrievable(): continue
            if r.scope == "global": pass
            elif r.scope == "workspace" and r.workspace_id != ws_id: continue
            elif r.scope == "session" and r.session_id != session_id: continue
            elif r.scope == "task":
                if not session_id or r.session_id != session_id: continue
            if memory_type and r.memory_type != memory_type: continue
            results.append(r)
            if len(results) >= limit:
                break
        return [r.to_dict() for r in results]

    def search(self, ws_id: str, query: str, limit: int = 10) -> list[dict]:
        """Search all lifecycle records for the memory-management surface."""
        ws_id = self._validated_ws_id(ws_id)
        limit = max(1, min(int(limit), 100))
        records = [record.to_dict() for record in self.list_all(ws_id)]
        if not str(query or "").strip():
            return records[:limit]
        from core.context.unified_retriever import rank_documents
        return rank_documents(str(query), records, top_k=limit)

    def find_conflicts(self, record: MemoryRecord) -> list[MemoryRecord]:
        """Find conflicting records with same scope+type+similar content."""
        existing = self.list_all(record.workspace_id)
        conflicts = []
        for r in existing:
            if r.memory_id == record.memory_id: continue
            if r.scope != record.scope: continue
            if r.memory_type != record.memory_type: continue
            if record.scope == "session" and r.session_id != record.session_id: continue
            if record.scope == "task" and r.task_id != record.task_id: continue
            if r.status not in ("active", "pending"): continue
            existing_text = r.summary or r.content
            candidate_text = record.summary or record.content
            if _text_similarity(existing_text, candidate_text) > 0.55:
                conflicts.append(r)
        return conflicts


# ── Write Gate ──

class MemoryWriteGate:
    """All memory writes must go through this gate."""

    def __init__(self, store: MemoryStore = None):
        self.store = store or MemoryStore()

    def write(self, candidate: MemoryRecord, gate_mode: str | None = None) -> dict:
        """Gate a memory write. Returns dict with ok, status, memory_id, rejected, error.

        v3.10: Returns unified dict for all callers.
        gate_mode: "rule_only" | "llm_first" — controls whether LLM quality gating is applied.
        """
        # 1. Workspace required
        if not candidate.workspace_id:
            return {"ok": False, "status": "rejected", "memory_id": "",
                    "rejected": True, "error": "workspace_id is required",
                    "gate_mode": gate_mode}
        try:
            from workspace.ids import validate_workspace_id
            candidate.workspace_id = validate_workspace_id(candidate.workspace_id)
        except Exception:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "invalid_workspace_id",
                    "gate_mode": gate_mode}

        gate_mode = gate_mode or get_memory_gate_mode(candidate.workspace_id)
        if gate_mode not in _VALID_GATE_MODES:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "invalid_gate_mode", "gate_mode": gate_mode}
        if candidate.scope not in _VALID_SCOPES:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "invalid_memory_scope", "gate_mode": gate_mode}
        if candidate.memory_type not in _VALID_MEMORY_TYPES:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "invalid_memory_type", "gate_mode": gate_mode}
        if candidate.scope == "session" and not candidate.session_id:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "session_id_required", "gate_mode": gate_mode}
        if candidate.scope == "task" and not candidate.task_id:
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "task_id_required", "gate_mode": gate_mode}

        # 2. Secret rejection on original content before redaction; otherwise
        # redaction can hide the exact pattern from the detector.
        persistable_payload = {
            "content": candidate.content,
            "summary": candidate.summary,
            "source_ref": candidate.source_ref,
            "citations": candidate.citations,
            "metadata": candidate.metadata,
        }
        if _contains_secret_pattern(persistable_payload):
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "content contains secret-like patterns, rejected",
                    "gate_mode": gate_mode}
        if _is_low_value_memory(candidate):
            candidate.status = "rejected"
            candidate.redacted = True
            self.store._save(candidate)
            return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                    "rejected": True, "error": "low_value_memory",
                    "gate_mode": gate_mode}

        # 3. Redaction
        candidate.content = _redact(candidate.content)
        candidate.summary = _redact(candidate.summary)

        # Agent and subagent claims are proposals until the selected gate makes
        # an explicit decision. Confidence alone is never proof.
        is_subagent = candidate.created_by == "subagent" or candidate.source == "subagent"
        is_agent_generated = candidate.source in ("agent_suggestion", "subagent") or is_subagent
        if is_agent_generated:
            candidate.status = "pending"

        # 6b. Auto-confirm only explicit user/manual confirmations.
        # Agent/LLM/subagent suggestions remain pending even when confidence is
        # high; confidence is a ranking signal, not proof of durable truth.
        _auto_confirm_types = {"operational_fact", "artifact_summary", "user_preference"}
        _auto_sources = {"user", "manual_confirm"}
        if (
            candidate.status == "pending"
            and candidate.memory_type in _auto_confirm_types
            and candidate.confidence >= 0.5
            and candidate.source in _auto_sources
        ):
            candidate.status = "active"

        warnings: list[dict] = []

        # 7. LLM-first quality gate for agent-generated memories.
        # User-confirmed/manual memories are explicit user intent and must not
        # be rejected by an LLM classifier.
        if gate_mode == "llm_first" and is_agent_generated:
            accepted, skipped = _llm_gate_record(candidate)
            if accepted is None:
                candidate.status = "pending"
                warnings.extend(skipped)
            elif not accepted:
                reason = skipped[0].get("reason", "llm_gate_rejected") if skipped else "llm_gate_rejected"
                candidate.status = "rejected"
                candidate.redacted = True
                self.store._save(candidate)
                return {"ok": False, "status": candidate.status, "memory_id": candidate.memory_id,
                        "rejected": True, "error": reason, "gate_mode": gate_mode,
                        "warnings": skipped}
            else:
                score = int(candidate.metadata.get("llm_score", 0) or 0)
                candidate.status = "pending" if is_subagent or score < 4 else "active"
                warnings.extend(skipped)

        # 8. Conflict detection
        conflicts = self.store.find_conflicts(candidate)
        if conflicts:
            duplicates = [
                existing for existing in conflicts
                if _text_similarity(
                    existing.content or existing.summary,
                    candidate.content or candidate.summary,
                ) >= 0.9
            ]
            if duplicates:
                existing = duplicates[0]
                return {
                    "ok": True,
                    "status": existing.status,
                    "memory_id": existing.memory_id,
                    "rejected": False,
                    "duplicate": True,
                    "duplicate_of": existing.memory_id,
                    "gate_mode": gate_mode,
                }
            active_conflicts = [c for c in conflicts if c.status == "active"]
            if active_conflicts:
                group = f"cg-{uuid.uuid4().hex[:12]}"
                candidate.status = "conflict"
                candidate.conflict_group = group
                candidate.metadata["conflict_memory_ids"] = [c.memory_id for c in active_conflicts]
                for existing in active_conflicts:
                    existing.conflict_group = group
                    existing.updated_at = _now()
                    self.store._save(existing)

        # 9. Persist
        candidate.redacted = True
        self.store._save(candidate)
        result = {"ok": True, "status": candidate.status, "memory_id": candidate.memory_id,
                  "rejected": False, "conflict": candidate.status == "conflict",
                  "gate_mode": gate_mode}
        if warnings:
            result["warnings"] = warnings
        return result


# ── Promotion ──

def confirm_memory(ws_id: str, memory_id: str) -> dict:
    store = MemoryStore()
    rec = store.get(ws_id, memory_id)
    if not rec: return {"ok": False, "error": "not found"}
    if rec.status not in ("pending", "conflict"):
        return {"ok": False, "error": f"cannot confirm status {rec.status}"}
    # Resolve conflicts: expire conflicting active memories in same group
    if rec.conflict_group:
        for r in store.list_all(ws_id):
            if r.conflict_group == rec.conflict_group and r.memory_id != rec.memory_id and r.status == "active":
                r.status = "expired"; store._save(r)
    rec.status = "active"; rec.updated_at = _now()
    store._save(rec)
    _emit_event(ws_id, rec, "memory_confirmed")
    return {"ok": True, "status": "active"}

def reject_memory(ws_id: str, memory_id: str) -> dict:
    store = MemoryStore()
    rec = store.get(ws_id, memory_id)
    if not rec: return {"ok": False, "error": "not found"}
    rec.status = "rejected"; rec.updated_at = _now()
    store._save(rec)
    _emit_event(ws_id, rec, "memory_rejected")
    return {"ok": True, "status": "rejected"}

def expire_memory(ws_id: str, memory_id: str) -> dict:
    store = MemoryStore()
    rec = store.get(ws_id, memory_id)
    if not rec: return {"ok": False, "error": "not found"}
    rec.status = "expired"; rec.updated_at = _now()
    store._save(rec)
    _emit_event(ws_id, rec, "memory_expired")
    return {"ok": True, "status": "expired"}


# ── Helpers ──

def _redact(text: str) -> str:
    try:
        from core.tools.redaction import redact_string
        return redact_string(text)
    except Exception:
        for kw in _REDACT_KEYS:
            text = _obfuscate_kv(text, kw)
        return text

def _obfuscate_kv(text: str, key: str) -> str:
    import re
    return re.sub(rf'({key}\s*[=:]\s*)(\S+)', r'\1[REDACTED]', text, flags=re.I)

def _contains_secret_pattern(data) -> bool:
    try:
        from core.tools.redaction import contains_secret
        return contains_secret(data)
    except Exception:
        import re
        text = str(data)
        patterns = [r'sk-[a-zA-Z0-9]{20,}', r'Bearer\s+[a-zA-Z0-9\-_\.]{20,}',
                    r'AKIA[A-Z0-9]{16}', r'ghp_[a-zA-Z0-9]{36}']
        for p in patterns:
            if re.search(p, text): return True
        return False


def _is_low_value_memory(record: MemoryRecord) -> bool:
    # Check summary and content independently — concatenating them can
    # hide generic content (e.g. "completed" + "completed." → "completed completed.").
    generic_words = {"", "started", "completed", "ok", "true", "false", "success", "failed", "done", "finish", "finished"}
    content = (record.content or "").strip()
    if not content:
        return True
    for text in (record.content, record.summary):
        text = (text or "").strip().lower().rstrip(".。!！?？,，;；")
        if not text:
            continue
        if text in generic_words:
            return True
        # Check after common separators (e.g. "workspace.file: completed" → "completed")
        for sep in (": ", ":", " — ", " - "):
            if sep in text:
                after = text.split(sep, 1)[1].strip()
                if after in generic_words:
                    return True
                after_first = after.split()[0] if after else ""
                if after_first in {"completed", "started", "finished", "success", "failed", "ok", "done", "running", "executed"} and len(after) <= len(after_first) + 8:
                    return True
    full = " ".join([record.summary or "", record.content or ""]).strip().lower()
    if record.memory_type == "task_pattern":
        import re
        generic_task_patterns = [
            r"task\s+'?[\w\-]+'?\s+completed\s+successfully",
            r"task completed successfully",
            r"result:\s*search completed successfully",
        ]
        if any(re.search(p, full) for p in generic_task_patterns):
            return True
    if len(full) < 12 and record.source in ("agent_suggestion", "task", "subagent"):
        return True
    return False

def _llm_gate_record(record: MemoryRecord) -> tuple[Optional[bool], list[dict]]:
    """Run LLM quality gate on a single memory record.

    If the record already has an llm_score from the planner's batch
    evaluation (stored in candidate.metadata during planning), reuse it
    instead of calling the LLM again.
    """
    try:
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate
        from agent.runtime.memory_write.models import MemoryCandidate

        # If planner already evaluated this candidate via batch LLM,
        # use the cached score — avoid double LLM call
        if record.metadata and isinstance(record.metadata, dict):
            cached_score = record.metadata.get("llm_score")
            if cached_score is not None:
                record.metadata["llm_score"] = int(cached_score)
                cached_keep = record.metadata.get("llm_keep", True)
                if cached_keep and int(cached_score) >= 3:
                    cached_summary = record.metadata.get("llm_summary", "")
                    if cached_summary:
                        record.summary = str(cached_summary)[:200]
                    return True, []
                return False, [{"reason": f"llm_score_too_low ({cached_score})"}]

        candidate = MemoryCandidate(
            candidate_id=record.memory_id,
            memory_type=record.memory_type,
            content=record.content,
            source=record.source,
            task_id=record.task_id,
            confidence=record.confidence,
        )
        accepted, skipped = MemoryLLMGate().gate([candidate])
        if accepted:
            meta = accepted[0].metadata or {}
            summary = meta.get("summary") or meta.get("llm_summary")
            if summary:
                record.summary = str(summary)[:200]
            record.metadata.update(meta)
            return True, skipped
        if any(item.get("reason") == "llm_gate_unavailable" for item in skipped):
            return None, skipped
        return False, skipped
    except Exception:
        return None, [{"reason": "llm_gate_unavailable"}]

def _text_similarity(a: str, b: str) -> float:
    def _tokens(text: str) -> set[str]:
        import re
        normalized = (text or "").lower().strip()
        if not normalized:
            return set()
        words = set(re.findall(r"[a-z0-9_./:-]+", normalized))
        cjk = re.findall(r"[\u4e00-\u9fff]", normalized)
        if cjk:
            words.update(cjk)
            words.update("".join(cjk[i:i + 2]) for i in range(len(cjk) - 1))
        if not words and normalized:
            compact = re.sub(r"\s+", "", normalized)
            words.update(compact[i:i + 3] for i in range(max(1, len(compact) - 2)))
        return {w for w in words if w}

    a_words = _tokens(a)
    b_words = _tokens(b)
    if not a_words or not b_words:
        return 0
    overlap = len(a_words & b_words)
    jaccard = overlap / len(a_words | b_words)
    containment = overlap / min(len(a_words), len(b_words))
    return max(jaccard, containment)

def _emit_event(ws_id: str, rec: MemoryRecord, event_type: str):
    try:
        from agent.runtime.durable import RuntimeEvent
        from agent.runtime.durable.store import append_event
        append_event(RuntimeEvent(
            event_id=f"evt-mem-{uuid.uuid4().hex[:8]}",
            task_id=rec.task_id, workspace_id=ws_id,
            session_id=rec.session_id, run_id="",
            type=event_type, status="ok",
            title=f"Memory {rec.memory_id[:8]}: {event_type}",
            summary=rec.summary[:200],
            payload_redacted={"memory_id": rec.memory_id, "memory_type": rec.memory_type},
        ))
    except Exception:
        logging.getLogger("memory_governance.events").debug(
            "memory lifecycle event append failed", exc_info=True,
        )


def get_memory_gate_mode(workspace_id: str) -> str:
    """Read memory_gating setting from workspace state.
    Returns 'rule_only' or 'llm_first'. """
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        raw = state.get("memory_gating", "").strip().lower()
        if raw == "llm_first":
            return "llm_first"
        if raw == "rule_only":
            return "rule_only"
    except Exception:
        logging.getLogger("memory_governance.settings").debug(
            "memory gate mode lookup failed", exc_info=True,
        )
    return "rule_only"
