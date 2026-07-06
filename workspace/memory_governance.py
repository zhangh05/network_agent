# workspace/memory_governance.py
"""Memory Governance — schema, gate, retrieval, conflict detection.

Memory JSON files are read-model projections. GraphStore projection events are
written first and are the SSOT for memory write acceptance.
"""

from __future__ import annotations
import json, time as _time, hashlib, uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Literal
from workspace.run_store import WS_ROOT
from workspace.atomic_io import atomic_write_json
from agent.runtime.utils import from_iso, now_iso, to_iso

Scope = Literal["global","workspace","session","task"]
MemoryType = Literal[
    "user_preference","task_pattern","tool_learning","error_lesson",
    "artifact_summary","operational_fact","profile","knowledge_note",
]
MemoryStatus = Literal["pending","active","rejected","expired","conflict"]
MemorySource = Literal[
    "user","tool","file","manual_confirm","agent_suggestion","subagent",
    "llm_tool","task","action","user_signal",
]

_REDACT_KEYS = {"password","token","api_key","secret","credential","key","auth"}

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
        return self._dir(ws_id) / f"{memory_id}.json"

    def _save(self, record: MemoryRecord):
        """Internal write — gate checks are enforced by MemoryWriteGate."""
        record.workspace_id = self._validated_ws_id(record.workspace_id)
        d = self._dir(record.workspace_id); d.mkdir(parents=True, exist_ok=True)
        from core.graph.projection_events import append_memory_written
        event_id = append_memory_written(
            workspace_id=record.workspace_id,
            memory_id=record.memory_id,
            record=record.to_dict(),
        )
        record.metadata = dict(record.metadata or {})
        record.metadata["ssot_event_id"] = event_id
        record.metadata["projection_of"] = "GraphStore"
        atomic_write_json(self._path(record.workspace_id, record.memory_id), record.to_dict())

    def delete_file(self, ws_id: str, memory_id: str) -> bool:
        """Physically delete a memory record file."""
        p = self._path(ws_id, memory_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def get(self, ws_id: str, memory_id: str) -> Optional[MemoryRecord]:
        p = self._path(ws_id, memory_id)
        if not p.exists(): return None
        try: return MemoryRecord.from_dict(json.loads(p.read_text()))
        except Exception: return None

    def list_all(self, ws_id: str) -> list[MemoryRecord]:
        d = self._dir(ws_id)
        if not d.exists(): return []
        recs = []
        for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try: recs.append(MemoryRecord.from_dict(json.loads(f.read_text())))
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

    def find_conflicts(self, record: MemoryRecord) -> list[MemoryRecord]:
        """Find conflicting records with same scope+type+similar content."""
        existing = self.list_all(record.workspace_id)
        conflicts = []
        for r in existing:
            if r.memory_id == record.memory_id: continue
            if r.scope != record.scope: continue
            if r.memory_type != record.memory_type: continue
            if r.status not in ("active", "pending"): continue
            # Simple similarity check
            if _text_similarity(r.summary, record.summary) > 0.55:
                conflicts.append(r)
        return conflicts


# ── Write Gate ──

class MemoryWriteGate:
    """All memory writes must go through this gate."""

    def __init__(self, store: MemoryStore = None):
        self.store = store or MemoryStore()

    def write(self, candidate: MemoryRecord, gate_mode: str = "rule_only") -> dict:
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

        # 2. Secret rejection on original content before redaction; otherwise
        # redaction can hide the exact pattern from the detector.
        if _contains_secret_pattern(candidate.content):
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

        # 4. Subagent can only create pending
        if candidate.created_by == "subagent" and candidate.status != "pending":
            candidate.status = "pending"

        # 5. Agent suggestion default pending unless high confidence
        if candidate.source == "agent_suggestion" and candidate.confidence < 0.8:
            candidate.status = "pending"

        # 6. Low confidence default pending
        if candidate.confidence < 0.3:
            candidate.status = "pending"

        # 6b. Auto-confirm only explicit user/manual confirmations.
        # Agent/LLM/subagent suggestions remain pending even when confidence is
        # high; confidence is a ranking signal, not proof of durable truth.
        _auto_confirm_types = {"operational_fact", "artifact_summary", "user_preference"}
        _auto_sources = {"user", "manual_confirm"}
        if (
            candidate.status == "pending"
            and candidate.memory_type in _auto_confirm_types
            and candidate.confidence >= 0.7
            and candidate.source in _auto_sources
        ):
            candidate.status = "active"

        warnings: list[dict] = []

        # 7. LLM-first quality gate for agent-generated memories.
        # User-confirmed/manual memories are explicit user intent and must not
        # be rejected by an LLM classifier.
        if gate_mode == "llm_first" and candidate.source in ("agent_suggestion", "subagent"):
            accepted, skipped = _llm_gate_record(candidate)
            if not accepted:
                reason = skipped[0].get("reason", "llm_gate_rejected") if skipped else "llm_gate_rejected"
                return {"ok": False, "status": "rejected", "memory_id": candidate.memory_id,
                        "rejected": True, "error": reason, "gate_mode": gate_mode}
            warnings.extend(skipped)

        # 8. Conflict detection
        conflicts = self.store.find_conflicts(candidate)
        if conflicts:
            for c in conflicts:
                if c.status == "active":
                    candidate.status = "conflict"
                    candidate.conflict_group = f"cg-{_time.time():.0f}"

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

def _contains_secret_pattern(text: str) -> bool:
    try:
        from core.tools.redaction import contains_secret
        return contains_secret(text)
    except Exception:
        import re
        patterns = [r'sk-[a-zA-Z0-9]{20,}', r'Bearer\s+[a-zA-Z0-9\-_\.]{20,}',
                    r'AKIA[A-Z0-9]{16}', r'ghp_[a-zA-Z0-9]{36}']
        for p in patterns:
            if re.search(p, text): return True
        return False


def _is_low_value_memory(record: MemoryRecord) -> bool:
    text = " ".join([record.summary or "", record.content or ""]).strip().lower()
    if not text:
        return True
    if record.memory_type == "task_pattern":
        import re
        generic_task_patterns = [
            r"task\s+'?[\w\-]+'?\s+completed\s+successfully",
            r"task completed successfully",
            r"result:\s*search completed successfully",
        ]
        if any(re.search(p, text) for p in generic_task_patterns):
            return True
    if len(text) < 12 and record.source in ("agent_suggestion", "task", "subagent"):
        return True
    return False

def _llm_gate_record(record: MemoryRecord) -> tuple[bool, list[dict]]:
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
                if cached_score >= 3:
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
            return True, skipped
        return False, skipped
    except Exception:
        return True, [{"reason": "llm_gate_unavailable_fallback"}]

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
        pass


def get_memory_gate_mode(workspace_id: str) -> str:
    """Read memory_gating setting from workspace state.
    Returns 'rule_only' or 'llm_first'. """
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        raw = state.get("memory_gating", "").strip().lower()
        if raw in ("llm_first", "llm", "llm-first"):
            return "llm_first"
    except Exception:
        pass
    return "rule_only"
