# agent/runtime/tool_planning/decision.py
"""ToolPlanningDecision — structured output of tool planning for a turn.

Every turn produces exactly one ToolPlanningDecision.
It captures: what capabilities were selected, which tools became visible,
which tools were blocked (and why), and the selection rationale.

This is the machine-readable answer to "why did the Agent use these tools?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agent.runtime.tool_planning.policy import POLICY_VERSION


@dataclass
class ToolPlanningDecision:
    """Structured decision record for one turn's tool plan.

    Populated from the deterministic planner and ToolPlanningPolicy.
    Written to ctx.metadata["tool_planning_decision"] for audit/inspection,
    and into the per-run decision report.
    """

    # ── Core identifiers ──

    # Which capability packages were selected for this turn
    capability_ids: list = field(default_factory=list)

    # Which module service manifests were activated
    module_ids: list = field(default_factory=list)

    # ── Tool visibility ──

    # Full list of tool_ids the LLM may see this turn.
    # The tool router MUST only expose these tools as callable functions.
    visible_tools: list = field(default_factory=list)

    # Tools the LLM is expected to call (strong signal from planner).
    # The LLM may skip these, but the planner considers them necessary.
    required_tools: list = field(default_factory=list)

    # Tools the LLM may optionally call — suggested but not required.
    optional_tools: list = field(default_factory=list)

    # Tools explicitly blocked for this turn, with reasons.
    # Each entry: {"tool_id": "...", "reason": "..."}
    blocked_tools: list = field(default_factory=list)

    # ── Safety flags ──

    # Whether local ops (host.shell.exec, host.powershell.exec) are
    # permitted in this turn. Requires explicit scene signal.
    local_ops_allowed: bool = False

    # Whether tool.catalog.search can expand the visible set mid-turn.
    catalog_expansion_allowed: bool = True

    # ── Rationale ──

    # Human-readable explanation of why these tools were chosen.
    selection_reason: str = ""

    # Policy version in effect when this decision was made.
    policy_version: str = POLICY_VERSION

    # ── Metadata ──

    # The raw capability route from CapabilityRouter (for audit)
    capability_route: Optional[dict] = None

    # Planner mode: "deterministic" | "llm" | "hybrid"
    planner_mode: str = "deterministic"

    # Planner version string from ToolPlannerV2 / deterministic_plan_tools
    planner_version: str = ""

    # Whether the plan passed validation
    valid: bool = True

    # Validation warnings (non-fatal issues)
    warnings: list = field(default_factory=list)

    # ── Serialization ──

    def to_dict(self) -> dict:
        """Serialise for decision reports and ctx.metadata.

        Sensitive fields are automatically redacted:
          - capability_route raw content is redacted (only structure preserved)
          - warnings/errors are truncated to 500 chars each
          - blocked_tools reasons are kept (they are structural, not content)
        """
        d: dict = {
            "capability_ids": list(self.capability_ids),
            "module_ids": list(self.module_ids),
            "visible_tools": list(self.visible_tools),
            "required_tools": list(self.required_tools),
            "optional_tools": list(self.optional_tools),
            "blocked_tools": list(self.blocked_tools),
            "local_ops_allowed": self.local_ops_allowed,
            "catalog_expansion_allowed": self.catalog_expansion_allowed,
            "selection_reason": _redact_reason(str(self.selection_reason)),
            "policy_version": self.policy_version,
            "planner_mode": self.planner_mode,
            "planner_version": self.planner_version,
            "valid": self.valid,
            "warnings": [
                str(w)[:500] for w in (self.warnings or [])
            ],
        }
        if self.capability_route:
            d["capability_route"] = _redact_capability_route(self.capability_route)
        return d

    # ── Factory ──

    @classmethod
    def from_plan(
        cls,
        plan: dict,
        capability_route: dict = None,
        policy: "ToolPlanningPolicy" = None,  # noqa: F821
    ) -> "ToolPlanningDecision":
        """Build a ToolPlanningDecision from a deterministic plan dict.

        Extracts visibility, blocking, and rationale from the planner output.
        """
        visible = list(plan.get("candidate_tools", []))
        steps = plan.get("tool_plan", [])
        capability_steps = plan.get("capability_plan", [])
        governance = plan.get("governance", {})
        visibility_meta = plan.get("visibility", {})

        # Split tools into required and optional based on step requirements
        required: list[str] = []
        optional: list[str] = []
        for step in steps:
            tools = list(step.get("tool_candidates", []))
            if step.get("required", False):
                required.extend(tools)
            else:
                optional.extend(tools)

        # Deduplicate while preserving order
        required = list(dict.fromkeys(required))
        optional = list(dict.fromkeys(
            [t for t in optional if t not in required]
        ))

        # Build blocked_tools from governance filtered entries
        blocked: list[dict] = []
        for category, tool_ids in governance.items():
            if isinstance(tool_ids, list) and category.endswith("_filtered"):
                reason = category.replace("_filtered", "").replace("_", " ")
                for tid in tool_ids:
                    blocked.append({"tool_id": str(tid), "reason": reason})

        local_ops = bool(visibility_meta.get("local_ops_enabled", False))
        pv = policy.policy_version if policy else POLICY_VERSION

        # Extract capability_ids from capability steps
        cap_ids = [
            str(s.get("capability_action", ""))
            for s in capability_steps
            if s.get("capability_action")
        ]

        return cls(
            capability_ids=list(dict.fromkeys(cap_ids)),
            module_ids=list(plan.get("module_ids", [])),
            visible_tools=visible,
            required_tools=required,
            optional_tools=optional,
            blocked_tools=blocked,
            local_ops_allowed=local_ops,
            catalog_expansion_allowed=True,
            selection_reason=str(plan.get("reason", "deterministic plan")),
            policy_version=pv,
            capability_route=capability_route,
            planner_mode=str(plan.get("mode", "deterministic")),
            planner_version=str(plan.get("planner_version", "")),
            valid=bool(plan.get("tool_planner", {}).get("valid", True)),
            warnings=list(plan.get("tool_planner", {}).get("warnings", [])),
        )


# ── Redaction helpers ──────────────────────────────────────────────────

_SENSITIVE_KEY_PATTERNS = (
    "secret", "password", "token", "api_key", "authorization",
    "credential", "private_key", "source_config", "raw_config",
    "raw_content", "full_text", "config_body", "file_content",
)


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(part in lower for part in _SENSITIVE_KEY_PATTERNS)


def _redact_reason(reason: str) -> str:
    """Truncate and sanitise the selection reason.

    Reasons are structural explanations (e.g. "user mentioned config analysis").
    We keep them but limit length to prevent accidental content leaks.
    """
    if not reason:
        return ""
    return str(reason)[:500]


def _redact_capability_route(route: dict) -> dict:
    """Redact a capability route to only keep structural fields.

    Capability routes contain routing information (package names, scores,
    reasons) — these are safe to keep. We strip any raw user content or
    large nested data.
    """
    if not isinstance(route, dict):
        return {}
    safe: dict = {}
    for key, value in route.items():
        if _is_sensitive_key(str(key)):
            continue
        if isinstance(value, dict):
            safe[str(key)] = _redact_capability_route(value)
        elif isinstance(value, list):
            safe[str(key)] = [
                _redact_capability_route(v) if isinstance(v, dict)
                else (str(v)[:200] if isinstance(v, str) else v)
                for v in value[:20]
            ]
        elif isinstance(value, str):
            safe[str(key)] = value[:1000]
        elif isinstance(value, (int, float, bool)):
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)[:200]
    return safe


def redact_decision_for_report(decision_dict: dict) -> dict:
    """Apply full redaction to a decision dict for external reports.

    This is stricter than to_dict() — it strips all potentially
    sensitive fields and keeps only the structural skeleton.
    """
    if not isinstance(decision_dict, dict):
        return {}
    out = dict(decision_dict)
    # Strip large text fields
    for field in ("selection_reason",):
        if field in out and isinstance(out[field], str):
            out[field] = out[field][:300]
    # Strip warnings that may contain raw output
    if "warnings" in out and isinstance(out["warnings"], list):
        out["warnings"] = [
            str(w)[:200] for w in out["warnings"]
        ]
    # Remove capability_route entirely from external reports
    # (internal audit can read it from ctx.metadata)
    out.pop("capability_route", None)
    return out
