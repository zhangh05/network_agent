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
from core.tools.tool_namespace import get_canonical_tool_id


class UnknownToolCallError(Exception):
    """Raised when LLM attempts to call a tool not in model-visible whitelist."""
    pass


class ToolArgumentParseError(Exception):
    """Raised when an LLM tool-call's arguments string is not valid JSON.

    Previously these errors were silently swallowed and `{"raw": ...}` was
    passed downstream, which made tool handlers fail with cryptic
    'missing required field' errors instead of telling the model that
    its JSON was malformed. Raising lets the loop surface a clear hint
    to the model so it can correct its output format.
    """
    pass


class ToolRouter:
    def __init__(self, registry: ToolRegistry = None, *, allowed_tool_ids=None):
        """Construct a ToolRouter.

        Use `ToolRouter.for_turn(registry, allowed_tool_ids)` for the
        per-turn pattern; pass `allowed_tool_ids` to bake the per-turn
        whitelist in at construction time.
        """
        self.registry = registry or ToolRegistry()
        self.model_visible_specs: list = []
        self.llm_name_map: dict = {}  # llm_safe_name → real_tool_id
        self.dispatch_delegate = None
        # v3.0 canonical-only: the allowed_tool_ids set is already a
        # set of canonical tool_ids; the safety filter is the
        # intersection with the registry-visible set.
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
            canonical_tool_id = get_canonical_tool_id(spec.tool_id)
            llm_name = to_llm_tool_name(canonical_tool_id)
            llm_spec = LLMToolSpec(
                name=llm_name,
                description=self._describe_for_llm(spec),
                parameters=spec.input_schema,
                real_tool_id=spec.tool_id,
            )
            self.model_visible_specs.append(llm_spec)
            self.llm_name_map[llm_name] = spec.tool_id
            for alias in self._llm_name_aliases(canonical_tool_id):
                self.llm_name_map.setdefault(alias, spec.tool_id)

    @staticmethod
    def _describe_for_llm(spec) -> str:
        """Build a readable LLM-facing tool description.

        Includes usage_hint and not_for from metadata so the LLM knows
        when to use (and NOT to use) each tool. Governance prefix is
        minimized to just risk + approval.
        """
        meta = getattr(spec, "metadata", {}) or {}
        canonical_tool_id = meta.get("canonical_tool_id") or get_canonical_tool_id(spec.tool_id)
        risk = getattr(spec, "risk_level", "low") or "low"
        approval = "⚠ approval required" if getattr(spec, "requires_approval", False) else ""

        # Read namespace usage hints
        usage = (meta.get("usage_hint") or "").strip()
        not_for = (meta.get("not_for") or "").strip()

        base = (spec.description or "").strip()
        parts = [base]
        if usage and usage not in base:
            parts.append(usage)
        if not_for and not_for not in base:
            parts.append(not_for)
        body = " | ".join(parts)

        # Minimal safety prefix: risk level + approval
        prefix_parts = [f"[risk={risk}"]
        if approval:
            prefix_parts.append(approval)
        prefix_parts.append("]")
        prefix = " ".join(prefix_parts)

        return f"{prefix} {body} | tool_id={canonical_tool_id}"

    @staticmethod
    def _llm_name_aliases(tool_id: str) -> set[str]:
        """Return tolerant aliases for common model underscore variants."""
        parts = [p for p in tool_id.split(".") if p]
        aliases: set[str] = set()
        if len(parts) >= 3:
            aliases.add("_".join(parts[:-1]) + "__" + parts[-1])
        if len(parts) == 2:
            aliases.add("_".join(parts))
        return aliases

    def apply_dynamic_visibility(self, allowed_tool_ids):
        """Restrict the LLM-visible whitelist to the given canonical tool_ids.

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
            eligible = {s.tool_id for s in self.registry.list_model_visible()}
            self._allowed_tool_ids = {
                t for t in allowed_tool_ids if t in eligible
            }
            self._dynamic_visibility = True
        self._build()

    def expand_dynamic_visibility(self, tool_ids) -> list[str]:
        """Add canonical tool_ids to the current turn's visible whitelist.

        Kept for explicit runtime-controlled updates only. LLM-visible catalog
        search was removed in v3.9.4; callers must pass canonical ids that are
        already present in the registry.
        """
        if not tool_ids:
            return []
        eligible = {s.tool_id for s in self.registry.list_model_visible()}
        additions = [t for t in tool_ids if t in eligible]
        if not additions:
            return []
        if self._allowed_tool_ids is None:
            # Full visibility is already active, so no rebuild is needed.
            return sorted(set(additions))
        before = set(self._allowed_tool_ids)
        self._allowed_tool_ids.update(additions)
        added = sorted(self._allowed_tool_ids - before)
        if added:
            self._dynamic_visibility = True
            self._build()
        return added

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

    def model_visible_tools_compact(
        self,
        core_tool_ids: set[str] | None = None,
    ) -> list:
        """Return OpenAI-format tool defs with compact non-core schemas.
        
        Core tools (always needed) get full schema. Non-core tools get
        compact schemas to save tokens. Full callable schemas are selected by
        the runtime, not by an LLM catalog-search tool.
        """
        core = core_tool_ids or set()
        result = []
        for spec in self.model_visible_specs:
            if spec.real_tool_id in core:
                result.append(spec.to_openai_function())
            else:
                result.append(spec.to_openai_function_compact())
        return result

    @staticmethod
    def resolve_tool_id(tool_id: str) -> str:
        """Return the canonical id for a tool reference.

        v3.0 canonical-only: there is no alias layer, so the input
        is already the canonical id. This is preserved as a stable
        indirection point for callers that feed tool references through it.
        """
        return tool_id

    @staticmethod
    def get_canonical_tool_id(tool_id: str) -> str:
        return get_canonical_tool_id(tool_id)

    def build_tool_call(self, raw_llm_tool_call) -> ToolCall:
        """Convert raw LLM tool_call to ToolCall with real_tool_id.

        Validates that the LLM tool name is in the model-visible whitelist.
        Raises UnknownToolCallError if the tool is not exposed to the model.
        """
        llm_name = raw_llm_tool_call.name if hasattr(raw_llm_tool_call, 'name') else raw_llm_tool_call.get("name", "")

        # Whitelist check: only allow tools that were explicitly exposed to LLM
        if llm_name not in self.llm_name_map:
            requested_tool_id = from_llm_tool_name(llm_name)
            canonical_id = get_canonical_tool_id(requested_tool_id)
            visible_canonical_ids = {s.real_tool_id for s in self.model_visible_specs}
            if canonical_id not in visible_canonical_ids:
                raise UnknownToolCallError(f"Tool not visible to model: {llm_name}")
            self.llm_name_map[llm_name] = canonical_id

        call_id = raw_llm_tool_call.id if hasattr(raw_llm_tool_call, 'id') else raw_llm_tool_call.get("id", "")
        args = raw_llm_tool_call.arguments if hasattr(raw_llm_tool_call, 'arguments') else raw_llm_tool_call.get("arguments", {})

        if isinstance(args, str):
            import json
            stripped = args.strip()
            # Empty arguments are allowed (some tools take no args).
            if not stripped:
                args = {}
            else:
                try:
                    args = json.loads(stripped)
                except Exception as e:
                    # v4.0: surface parse failure clearly so the model can
                    # fix the format. Previously this was silently wrapped
                    # in {"raw": ...} which masked the real error.
                    preview = stripped[:120]
                    raise ToolArgumentParseError(
                        f"Tool {llm_name} arguments are not valid JSON "
                        f"({type(e).__name__}: {e}); got: {preview!r}"
                    ) from e
                if not isinstance(args, dict):
                    raise ToolArgumentParseError(
                        f"Tool {llm_name} arguments must be a JSON object, "
                        f"got {type(args).__name__}"
                    )

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
                # Delegate may return core.tools.schemas.ToolResult, which
                # has status (not ok) + output (not top-level fields).
                if hasattr(raw, "status") and hasattr(raw, "output"):
                    output = getattr(raw, "output", {}) or {}
                    if isinstance(output, dict):
                        return ToolResult.from_handler_dict(
                            tool_id=tool_call.real_tool_id,
                            call_id=tool_call.call_id,
                            d={**output, "summary": getattr(raw, "summary", output.get("summary", "")),
                               "errors": list(getattr(raw, "errors", []) or []),
                               "warnings": list(getattr(raw, "warnings", []) or []),
                               "artifacts": list(getattr(raw, "artifact_ids", []) or [])},
                        )
            else:
                raw = self.registry.dispatch(tool_call.real_tool_id, tool_call.arguments, context)
            if isinstance(raw, dict):
                return ToolResult.from_handler_dict(
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
