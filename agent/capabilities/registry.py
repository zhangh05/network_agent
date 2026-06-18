# agent/capabilities/registry.py
"""CapabilityRegistry — the single source of truth for capabilities.

The registry is the canonical state for:
- Which capabilities exist
- Whether each is enabled / planned / disabled
- Which Module / Skill / Tool they expose
- What the safety contract says

ModuleRegistry / SkillRegistry / ToolRegistry / RuntimeSnapshot all
derive from this registry.
"""

from typing import Iterable, List, Optional

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityToolRef,
)


class CapabilityRegistry:
    """Registry of CapabilityManifests.

    Construction is explicit: pass a list of manifests. Use
    `get_default_capability_registry()` to get the built-in one.
    """

    def __init__(self, manifests: Optional[Iterable[CapabilityManifest]] = None):
        self._manifests: dict[str, CapabilityManifest] = {}
        if manifests:
            for m in manifests:
                self._manifests[m.capability_id] = m

    # ── Mutation ──

    def register(self, manifest: CapabilityManifest) -> None:
        if not manifest.capability_id:
            raise ValueError("CapabilityManifest.capability_id is required")
        self._manifests[manifest.capability_id] = manifest

    # ── Read ──

    def get(self, capability_id: str) -> Optional[CapabilityManifest]:
        return self._manifests.get(capability_id)

    def list_all(self) -> List[CapabilityManifest]:
        return list(self._manifests.values())

    def list_enabled(self) -> List[CapabilityManifest]:
        return [m for m in self._manifests.values() if m.status == "enabled"]

    def list_planned(self) -> List[CapabilityManifest]:
        return [m for m in self._manifests.values() if m.status == "planned"]

    def list_disabled(self) -> List[CapabilityManifest]:
        return [m for m in self._manifests.values() if m.status == "disabled"]

    # ── Enabled views ──

    def enabled_modules(self) -> List[dict]:
        out: list[dict] = []
        for m in self.list_enabled():
            out.append({
                "module_id": m.module.module_id,
                "name": m.name,
                "status": m.module.status,
                "service_path": m.module.service_path,
                "operations": list(m.module.operations),
                "description": m.module.description,
                "capability_id": m.capability_id,
            })
        return out

    def enabled_skills(self) -> List[dict]:
        out: list[dict] = []
        for m in self.list_enabled():
            for s in m.skills:
                if s.status != "enabled":
                    continue
                out.append({
                    "skill_id": s.skill_id,
                    "name": m.name,
                    "capability_id": m.capability_id,
                    "related_tools": list(s.related_tools),
                    "prompt_summary": s.prompt_summary,
                    "intent_patterns": list(s.intent_patterns),
                    "required_inputs": list(s.required_inputs),
                    "preconditions": list(s.preconditions),
                    "postconditions": list(s.postconditions),
                    "safety_rules": list(s.safety_rules),
                })
        return out

    def planned_skills(self) -> List[dict]:
        out: list[dict] = []
        for m in self.list_planned():
            for s in m.skills:
                if s.status != "planned":
                    continue
                out.append({
                    "skill_id": s.skill_id,
                    "name": m.name,
                    "capability_id": m.capability_id,
                    "related_tools": list(s.related_tools),
                    "prompt_summary": s.prompt_summary,
                })
        return out

    def enabled_tools(self) -> List[CapabilityToolRef]:
        """Return tool refs of all enabled capabilities, regardless of
        callable_by_llm. Used for ToolRegistry registration.

        Note: `callable_by_llm=False` tools are still registered for
        introspection / audit, but they MUST NOT appear in
        `visible_tool_ids()`.
        """
        out: list[CapabilityToolRef] = []
        for m in self.list_enabled():
            for t in m.tools:
                if t.status == "enabled":
                    out.append(t)
        return out

    def planned_modules(self) -> List[dict]:
        out: list[dict] = []
        for m in self.list_planned():
            out.append({
                "module_id": m.module.module_id,
                "name": m.name,
                "status": m.module.status,
                "capability_id": m.capability_id,
                "description": m.description,
            })
        return out

    def visible_tool_ids(self) -> List[str]:
        """Return tool_ids that are visible to the LLM.

        Visibility rules (strict — fail-closed):
        1. capability.status must be "enabled"
        2. tool.status must be "enabled"
        3. tool.callable_by_llm must be True
        4. tool.forbidden must be False
        5. tool.risk_level must NOT be "forbidden"

        Planned / disabled / non-LLM-callable tools MUST NOT appear.
        """
        out: list[str] = []
        for m in self.list_enabled():
            for t in m.tools:
                if t.status != "enabled":
                    continue
                if not t.callable_by_llm:
                    continue
                if t.forbidden:
                    continue
                if t.risk_level == "forbidden":
                    continue
                out.append(t.tool_id)
        return out

    def enabled_business_tool_ids(self) -> List[str]:
        """Same as visible_tool_ids() but restricted to capability tools
        (i.e., business tools such as network.config.translate and
        knowledge.search). Useful for RuntimeSnapshot to list them
        distinctly from general ToolRuntime tools.
        """
        return list(self.visible_tool_ids())

    def safety_summary(self) -> dict:
        """Aggregate the Safety Contract across all enabled capabilities.

        Returns a single dict the RuntimeSnapshot can paste into the
        prompt. If any enabled capability violates the safe default,
        the corresponding `true` flag is propagated.
        """
        agg = {
            "real_device_access": False,
            "allows_config_push": False,
            "produces_deployable_config": False,
            "may_fabricate_sources": False,
            "any_requires_human_review": False,
            "per_capability": [],
        }
        for m in self.list_enabled():
            s = m.safety
            agg["real_device_access"] = agg["real_device_access"] or s.real_device_access
            agg["allows_config_push"] = agg["allows_config_push"] or s.allows_config_push
            agg["produces_deployable_config"] = (
                agg["produces_deployable_config"] or s.produces_deployable_config
            )
            agg["may_fabricate_sources"] = agg["may_fabricate_sources"] or s.may_fabricate_sources
            agg["any_requires_human_review"] = (
                agg["any_requires_human_review"] or s.requires_human_review
            )
            agg["per_capability"].append({
                "capability_id": m.capability_id,
                "real_device_access": s.real_device_access,
                "allows_config_push": s.allows_config_push,
                "produces_deployable_config": s.produces_deployable_config,
                "may_fabricate_sources": s.may_fabricate_sources,
                "requires_human_review": s.requires_human_review,
                "notes": s.notes,
            })
        return agg

    def to_snapshot_dict(self) -> dict:
        """Serialize the registry into the shape RuntimeSnapshot consumes.

        This is the contract that ties the truth-source (registry) to
        the consumer (RuntimeSnapshot). It is a *projection*, never the
        primary state.
        """
        return {
            "enabled_capabilities": [
                {
                    "capability_id": m.capability_id,
                    "name": m.name,
                    "module_id": m.module.module_id,
                    "skills": [s.skill_id for s in m.skills if s.status == "enabled"],
                    "visible_tools": [t.tool_id for t in m.tools
                                       if t.status == "enabled"
                                       and t.callable_by_llm
                                       and not t.forbidden
                                       and t.risk_level != "forbidden"],
                }
                for m in self.list_enabled()
            ],
            "planned_capabilities": [
                {
                    "capability_id": m.capability_id,
                    "name": m.name,
                    "module_id": m.module.module_id,
                    "skills": [s.skill_id for s in m.skills if s.status == "planned"],
                }
                for m in self.list_planned()
            ],
            "all_tools": [t.tool_id for t in self.enabled_tools()],
            "visible_tools": self.visible_tool_ids(),
            "safety": self.safety_summary(),
        }
