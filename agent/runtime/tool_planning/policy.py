# agent/runtime/tool_planning/policy.py
"""ToolPlanningPolicy — hard contract for tool planning boundaries.

This is the codified "constitution" for tool execution:
  - What the system enforces (not what the LLM decides)
  - What the LLM can see, call, and discover
  - What requires explicit scene signals vs. what's always available

Rules are NOT suggestions — Executor must reject violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = "v1.0"


@dataclass
class ToolPlanningPolicy:
    """Hard contract that governs tool visibility and execution.

    Core invariants:
      1. LLM can ONLY see tools in visible_tools (enforced by router)
      2. LLM cannot call tools in blocked_tools (enforced by executor)
      3. Local ops require explicit scene signal (exec.run etc.)
      4. Catalog expansion adds tools to visible set but does NOT auto-execute
      5. User overrides go through governance before execution
    """

    policy_version: str = POLICY_VERSION

    # ── Hard boundaries ──

    # If True, executor MUST reject any tool call where tool_id is not in
    # the current visible_tool_ids set. This is the primary safety gate.
    enforce_visible_set: bool = True

    # If True, executor MUST reject calls to any tool in blocked_tools.
    # Each entry must have a mandatory reason.
    enforce_blocked_set: bool = True

    # If True, local ops tools (exec.run, exec.run)
    # can only appear in visible_tools when the scene explicitly requires
    # local operations. Even then they still go through approval.
    local_ops_require_scene: bool = True

    # ── Catalog expansion ──

    # If True, successful tool.catalog.search results can expand the
    # visible tool set for the current turn.
    catalog_expansion_adds_visible: bool = True

    # If True, tools discovered through catalog search require the LLM
    # to make a SEPARATE tool call — they are NOT auto-executed.
    # This prevents "search and execute" as a single step.
    catalog_expansion_requires_additional_call: bool = True

    # Bound prompt growth and prevent a directory search from turning into
    # effective full-catalog exposure.
    catalog_expansion_max_tools: int = 8

    # ── Override policy ──

    # If True, user-explicit tool overrides get highest priority in
    # the tool plan, but still go through governance/approval/risk.
    user_override_is_highest_priority: bool = True

    # ── Tool-specific blocks ──

    # Blocked tools with mandatory reasons.
    # Format: {tool_id: reason_string}
    # Executor checks this before any tool dispatch.
    blocked_tools: dict = field(default_factory=dict)

    # ── Per-run mutable state (set by planner, not in constructor) ──

    # Filled at plan time: which tools are visible for this turn
    visible_tool_ids: list = field(default_factory=list, repr=False)

    # Filled at plan time: which tools are explicitly blocked for this turn
    turn_blocked: list = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        """Serialise policy for decision reports and audits."""
        return {
            "policy_version": self.policy_version,
            "enforce_visible_set": self.enforce_visible_set,
            "enforce_blocked_set": self.enforce_blocked_set,
            "local_ops_require_scene": self.local_ops_require_scene,
            "catalog_expansion_adds_visible": self.catalog_expansion_adds_visible,
            "catalog_expansion_requires_additional_call": (
                self.catalog_expansion_requires_additional_call
            ),
            "catalog_expansion_max_tools": self.catalog_expansion_max_tools,
            "user_override_is_highest_priority": self.user_override_is_highest_priority,
            "blocked_tools": dict(self.blocked_tools),
            "visible_tool_ids": list(self.visible_tool_ids),
            "turn_blocked": list(self.turn_blocked),
        }

    def is_callable(self, tool_id: str) -> tuple[bool, str]:
        """Check whether a tool call is permitted under this policy.

        Returns (allowed: bool, reason: str).
        """
        if self.enforce_blocked_set:
            if tool_id in self.blocked_tools:
                return False, f"policy_blocked: {self.blocked_tools[tool_id]}"

        if self.enforce_visible_set and self.visible_tool_ids:
            if tool_id not in self.visible_tool_ids:
                return False, "not_in_visible_set"

        return True, "ok"

    def turn_catalog_expansion_permitted(self) -> bool:
        """Whether the LLM may discover new tools via tool.catalog.search."""
        return self.catalog_expansion_adds_visible

    @classmethod
    def default(cls) -> "ToolPlanningPolicy":
        """Return the production-default policy."""
        return cls()
