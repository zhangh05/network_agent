# agent/protocol/tool_result.py
"""ToolResult — tool execution result, the runtime / LLM contract.

v0.8.2 enhancement: ToolResult now carries the v0.7.1 capability fields
(artifacts, source_count, manual_review_count, metadata, data) as
**structured** fields, and gains `from_module_result()` to project a
ModuleResult into a ToolResult. The legacy `content` (str) field is
preserved for backward compatibility.

Three contracts (intentionally distinct):
  - ModuleResult  : business output contract, produced by a Module
                    (agent.modules.<x>.service)
  - ToolResult    : runtime / LLM tool-result contract, produced by a
                    Tool handler (agent.modules.<x>.tools) wrapping a
                    Module service call
  - AgentResult   : turn-level audit / UI contract, holds the list of
                    standardized tool_calls (the per-call projection
                    of ToolResult)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.protocol.module_result import ModuleResult


# Max serialized length of `content` when it is a string. The legacy
# code used 2000 chars; we keep that for backward compatibility.
CONTENT_MAX_LEN = 2000


@dataclass
class ToolResult:
    """ToolResult — wraps a ModuleResult into the runtime / LLM contract."""

    # Core identity
    call_id: str = ""
    tool_id: str = ""
    # Outcome
    ok: bool = False
    summary: str = ""
    # Legacy: serialized text representation. We still populate it
    # so v0.7.x callers (e.g. trace recorder) keep working.
    content: str = ""
    # Structured payload (ModuleResult.data). v0.8.2 NEW.
    data: dict = field(default_factory=dict)
    # v0.7.1 capability fields, now first-class on the dataclass
    artifacts: list = field(default_factory=list)
    source_count: Optional[int] = None
    manual_review_count: Optional[int] = None
    # Standard diagnostics
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # Raw ModuleResult-like fields (kept as a dict for legacy
    # consumers; equal to dict(to_module_result(...).to_dict()) for
    # capability tools)
    raw: dict = field(default_factory=dict)
    # Capability-specific auxiliary data (elapsed_ms, quality_summary,
    # audit, build_commit, ...). NOT part of the public contract
    # beyond "exists; opaque contents".
    metadata: dict = field(default_factory=dict)

    # ── Serialization ──

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict. Missing fields fall back to defaults
        so consumers can rely on the field set."""
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "ok": self.ok,
            "summary": self.summary,
            "content": self.content,
            "data": dict(self.data),
            "artifacts": list(self.artifacts),
            "source_count": self.source_count,
            "manual_review_count": self.manual_review_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "raw": dict(self.raw),
        }

    # ── Factory: from ModuleResult ──

    @classmethod
    def from_module_result(
        cls,
        tool_id: str,
        call_id: str,
        module_result: "ModuleResult",
        *,
        content_max_len: int = CONTENT_MAX_LEN,
    ) -> "ToolResult":
        """Build a ToolResult from a ModuleResult.

        Mapping:
          - call_id / tool_id     : from arguments
          - ok                    : module_result.ok
          - summary               : module_result.summary
          - data                  : module_result.data  (NEW v0.8.2)
          - artifacts             : module_result.artifacts
          - source_count          : module_result.data.get("source_count")
          - manual_review_count   : module_result.data.get("manual_review_count")
          - errors                : module_result.errors
          - warnings              : module_result.warnings
          - metadata              : module_result.metadata
          - content               : JSON-encoded payload (truncated to
                                     content_max_len for backward compat)
          - raw                   : dict(module_result.to_dict())
        """
        mr = module_result
        # Compute source_count / manual_review_count using the
        # module's own helpers (handles fallback to metadata).
        sc = mr.source_count()
        mrc = mr.manual_review_count()

        # Build a stable legacy `content` field. It mirrors what
        # v0.7.x tool handlers used to return, so trace recorders /
        # UIs that read `content` keep working.
        legacy_payload: dict[str, Any] = {
            "ok": mr.ok,
            "summary": mr.summary,
        }
        # Forward the top-level keys from data into the legacy
        # content payload (backward compat with v0.7.1 trace).
        for k, v in mr.data.items():
            if k in ("manual_review_count", "source_count"):
                continue  # already on ToolResult fields
            legacy_payload[k] = v
        if mr.artifacts:
            legacy_payload["artifacts"] = [
                {
                    "artifact_id": a.get("artifact_id", ""),
                    "artifact_type": a.get("artifact_type", ""),
                    "title": a.get("title", ""),
                }
                for a in mr.artifacts[:3]
            ]
        if mr.errors:
            legacy_payload["errors"] = list(mr.errors)[:5]
        if mr.warnings:
            legacy_payload["warnings"] = list(mr.warnings)[:5]
        content_str = json.dumps(legacy_payload, ensure_ascii=False)[:content_max_len]

        return cls(
            call_id=call_id,
            tool_id=tool_id,
            ok=mr.ok,
            summary=mr.summary,
            content=content_str,
            data=dict(mr.data),
            artifacts=list(mr.artifacts),
            source_count=sc,
            manual_review_count=mrc,
            errors=list(mr.errors),
            warnings=list(mr.warnings),
            metadata=dict(mr.metadata),
            raw=mr.to_dict(),
        )

    # ── Backward-compat dict-style fallback (v0.7.x tool handlers
    #    still return a plain dict; we accept that too). ──

    @classmethod
    def from_legacy_dict(
        cls,
        tool_id: str,
        call_id: str,
        d: dict,
    ) -> "ToolResult":
        """Build a ToolResult from the legacy dict shape returned by
        v0.7.x tool handlers. New code should use
        `from_module_result`; this adapter exists so the loop / registry
        never crashes on older hand-rolled handlers.
        """
        return cls(
            call_id=call_id,
            tool_id=tool_id,
            ok=bool(d.get("ok", False)),
            summary=str(d.get("summary", ""))[:CONTENT_MAX_LEN],
            content=str(d.get("content", ""))[:CONTENT_MAX_LEN]
                    if not isinstance(d.get("content"), (dict, list))
                    else json.dumps(d.get("content"), ensure_ascii=False)[:CONTENT_MAX_LEN],
            data=(d.get("data") if isinstance(d.get("data"), dict)
                  else (d.get("content") if isinstance(d.get("content"), dict)
                        else {})),
            artifacts=list(d.get("artifacts") or []),
            source_count=(int(d["source_count"]) if d.get("source_count") is not None
                          else None),
            manual_review_count=(int(d["manual_review_count"])
                                 if d.get("manual_review_count") is not None
                                 else None),
            errors=list(d.get("errors") or []),
            warnings=list(d.get("warnings") or []),
            metadata=dict(d.get("metadata") or {}),
            raw=dict(d),
        )
