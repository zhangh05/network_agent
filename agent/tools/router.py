# agent/tools/router.py
"""ToolRouter — centralized tool name mapping and dispatch.

v1.0.3.1: the per-turn tool whitelist is now a per-instance
property, not a mutable shared global. Callers should construct a
fresh `ToolRouter.for_turn(registry, allowed_tool_ids)` for every
turn; mutating the shared instance (via apply_dynamic_visibility) was
unsafe under concurrent turns and caused cross-talk between turns.
"""

from agent.tools.schemas import LLMToolSpec
from agent.tools.registry import ToolRegistry
from agent.llm.tool_adapter import to_llm_tool_name, from_llm_tool_name
from agent.protocol.tool_call import ToolCall
from agent.protocol.tool_result import ToolResult


class UnknownToolCallError(Exception):
    """Raised when LLM attempts to call a tool not in model-visible whitelist."""
    pass


class ToolRouter:
    def __init__(self, registry: ToolRegistry = None, *, allowed_tool_ids=None):
        """Construct a ToolRouter.

        Use `ToolRouter.for_turn(registry, allowed_tool_ids)` for the
        per-turn pattern. Direct construction is kept for backward
        compat with tests / legacy call sites; pass `allowed_tool_ids`
        to bake the per-turn whitelist in at construction time.
        """
        self.registry = registry or ToolRegistry()
        self.model_visible_specs: list = []
        self.llm_name_map: dict = {}  # llm_safe_name → real_tool_id
        self.dispatch_delegate = None
        # v1.0.3.1: per-instance immutable whitelist
        if allowed_tool_ids is not None:
            eligible = {s.tool_id for s in self.registry.list_model_visible()}
            self._allowed_tool_ids: set[str] | None = {
                t for t in allowed_tool_ids if t in eligible
            }
            self._dynamic_visibility: bool = True
        else:
            self._allowed_tool_ids = None
            self._dynamic_visibility = False
        self._build()

    @classmethod
    def for_turn(cls, tool_registry: ToolRegistry, allowed_tool_ids=None) -> "ToolRouter":
        """Build a fresh ToolRouter for a single turn.

        This is the v1.0.3.1-recommended construction path. It produces
        an independent router (no shared mutable state), so two turns
        running concurrently cannot cross-talk on `allowed_tool_ids`.
        """
        return cls(tool_registry, allowed_tool_ids=allowed_tool_ids)

    def _build(self):
        visible = self.registry.list_model_visible()
        # If dynamic visibility is active, intersect with the allowlist.
        if self._allowed_tool_ids is not None:
            visible = [s for s in visible if s.tool_id in self._allowed_tool_ids]
        self.model_visible_specs = []
        self.llm_name_map = {}
        for spec in visible:
            llm_name = to_llm_tool_name(spec.tool_id)
            llm_spec = LLMToolSpec(
                name=llm_name,
                description=spec.description,
                parameters=spec.input_schema,
                real_tool_id=spec.tool_id,
            )
            self.model_visible_specs.append(llm_spec)
            self.llm_name_map[llm_name] = spec.tool_id

    def apply_dynamic_visibility(self, allowed_tool_ids):
        """Restrict the LLM-visible whitelist to the given tool_ids.

        Rules:
        - Only tools that are present in the underlying ToolRegistry's
          list_model_visible() are eligible; this is a safety net so
          caller cannot accidentally expose a forbidden / planned tool.
        - The final whitelist is the intersection
          registry_visible ∩ allowed_tool_ids.
        - Forbidden, disabled, or planned tools (which are already
          excluded by registry.list_model_visible()) remain excluded.
        - Pass None / empty set to disable dynamic visibility and
          fall back to the full registry view (v0.8 behavior).
        """
        if not allowed_tool_ids:
            self._allowed_tool_ids = None
            self._dynamic_visibility = False
        else:
            # Pre-validate: only keep ids that are actually visible
            # in the registry (so the safety filter runs first).
            eligible = {s.tool_id for s in self.registry.list_model_visible()}
            self._allowed_tool_ids = {t for t in allowed_tool_ids if t in eligible}
            self._dynamic_visibility = True
        self._build()

    @property
    def dynamic_visibility(self) -> bool:
        return self._dynamic_visibility

    @property
    def allowed_tool_ids(self) -> set[str] | None:
        return set(self._allowed_tool_ids) if self._allowed_tool_ids is not None else None

    @classmethod
    def from_turn_context(cls, context) -> "ToolRouter":
        if context and context.tool_router:
            return context.tool_router
        return cls()

    def model_visible_tools(self) -> list:
        """Return OpenAI-format tool definitions for LLM."""
        return [s.to_openai_function() for s in self.model_visible_specs]

    def build_tool_call(self, raw_llm_tool_call) -> ToolCall:
        """Convert raw LLM tool_call to ToolCall with real_tool_id.

        Validates that the LLM tool name is in the model-visible whitelist.
        Raises UnknownToolCallError if the tool is not exposed to the model.
        """
        llm_name = raw_llm_tool_call.name if hasattr(raw_llm_tool_call, 'name') else raw_llm_tool_call.get("name", "")

        # Whitelist check: only allow tools that were explicitly exposed to LLM
        if llm_name not in self.llm_name_map:
            raise UnknownToolCallError(f"Tool not visible to model: {llm_name}")

        call_id = raw_llm_tool_call.id if hasattr(raw_llm_tool_call, 'id') else raw_llm_tool_call.get("id", "")
        args = raw_llm_tool_call.arguments if hasattr(raw_llm_tool_call, 'arguments') else raw_llm_tool_call.get("arguments", {})

        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}

        real_tool_id = self.llm_name_map[llm_name]
        tc = ToolCall(
            call_id=call_id,
            llm_tool_name=llm_name,
            real_tool_id=real_tool_id,
            arguments=args,
        )
        return tc

    def dispatch(self, tool_call: ToolCall, context=None) -> ToolResult:
        """Execute tool call and return ToolResult."""
        try:
            delegate = self.dispatch_delegate
            if delegate:
                raw = delegate(tool_call, context)
                if isinstance(raw, ToolResult):
                    return raw
            else:
                raw = self.registry.dispatch(tool_call.real_tool_id, tool_call.arguments, context)
            if isinstance(raw, dict):
                return ToolResult.from_legacy_dict(
                    tool_id=tool_call.real_tool_id,
                    call_id=tool_call.call_id,
                    d=raw,
                )
            raw_get = lambda key, default=None: getattr(raw, key, default)
            raw_dict = {
                key: raw_get(key)
                for key in (
                    "ok",
                    "summary",
                    "artifacts",
                    "source_count",
                    "manual_review_count",
                    "errors",
                    "warnings",
                    "metadata",
                )
                if raw_get(key, None) is not None
            }
            return ToolResult(
                call_id=tool_call.call_id,
                tool_id=tool_call.real_tool_id,
                ok=raw_get("ok", False),
                summary=raw_get("summary", ""),
                content=str(raw)[:2000],
                artifacts=list(raw_get("artifacts", []) or []),
                source_count=raw_get("source_count", None),
                manual_review_count=raw_get("manual_review_count", None),
                errors=raw_get("errors", []),
                warnings=raw_get("warnings", []),
                metadata=dict(raw_get("metadata", {}) or {}),
                raw=raw_dict,
            )
        except Exception as e:
            return ToolResult(
                call_id=tool_call.call_id,
                tool_id=tool_call.real_tool_id,
                ok=False,
                summary=str(e)[:200],
                errors=[str(e)[:200]],
            )
