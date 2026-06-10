# agent/skills/selector.py
"""SkillSelector — per-turn skill selection driven by CapabilityRegistry.

v0.8.1 introduction.

Goals:
- Decide, on every turn, which skills the LLM should be told about
- Use the CapabilityRegistry (truth-source) for capability skills
- Keep `assistant_chat` always-on as the base
- Honor planned / disabled boundaries from the manifest
- Provide a `capability_discovery` pseudo-skill for "what can you do?"
- Never crash; on any error, return the v0.8 fallback (assistant_chat only)

Rules (rule-based, no LLM):
- `assistant_chat` is always injected.
- If the user message matches any `intent_patterns` of an enabled
  capability's skill → that skill is injected.
- If the user message looks like a capability-discovery question
  ("what can you do", "you have which capabilities", "list tools", etc.)
  → inject `capability_discovery` (a meta-skill that summarizes
  enabled capabilities; uses only public info, no planned tools).
- If no rule matches → return [assistant_chat] only.
- Planned skills MUST NOT be injected.
- Disabled skills MUST NOT be injected.
"""

from __future__ import annotations

from typing import Iterable, List, Optional


# ── Capability-discovery heuristics ──
CAPABILITY_DISCOVERY_PATTERNS: list[str] = [
    "你能做什么",
    "你能干啥",
    "你有什么能力",
    "有什么能力",
    "有哪些能力",
    "有什么工具",
    "有哪些工具",
    "你支持什么",
    "你都会啥",
    "help",
    "what can you do",
    "what are your capabilities",
    "list capabilities",
    "list tools",
    "your features",
    "what skills do you have",
    "your abilities",
]

# Per-capability extra keyword sets used by the selector in addition to
# the manifest's own `intent_patterns`. These are short-circuit hints
# for common phrasings and do not duplicate business logic.
EXTRA_KEYWORDS: dict[str, list[str]] = {
    "config_translation": [
        "翻译", "翻译配置", "配置翻译", "转配置", "转换成",
        "convert config", "translate config", "vendor",
        # Common vendor / artifact keywords that strongly suggest
        # config-translation intent. Conservative — only added where
        # there's little ambiguity.
        "cisco", "huawei", "h3c", "ruijie", "juniper",
        "acl",
    ],
    "knowledge_query": [
        "查知识", "查资料", "知识库", "rfc", "standard",
        "lookup", "search docs", "search docs", "find in",
    ],
}


class SkillSelector:
    """Rule-based per-turn skill selector.

    Stateless and re-entrant: instantiate freely per turn. No I/O, no LLM.
    """

    def __init__(self, capability_registry=None):
        self.capability_registry = capability_registry

    # ── Public API ──

    def select(
        self,
        user_message: str,
        *,
        capability_registry=None,
        base_skills: Optional[Iterable[str]] = None,
    ) -> List[str]:
        """Return the ordered list of skill_ids to inject for this turn.

        Always starts with `assistant_chat`. Order is preserved; deduped.
        """
        cap_reg = capability_registry or self.capability_registry
        # Default base: assistant_chat
        base = list(base_skills) if base_skills else ["assistant_chat"]
        try:
            return self._do_select(user_message or "", cap_reg, base)
        except Exception:
            # Never crash: fall back to base skills only.
            return [s for s in dict.fromkeys(base) if s]

    # ── Internals ──

    def _do_select(
        self,
        msg: str,
        cap_reg,
        base: list[str],
    ) -> List[str]:
        msg_l = (msg or "").lower()
        selected: list[str] = []
        seen: set[str] = set()

        def _push(s: str):
            if s and s not in seen:
                selected.append(s)
                seen.add(s)

        # 1. base skills (always)
        for s in base:
            _push(s)

        if not msg_l.strip():
            return selected

        # 2. capability discovery heuristic
        if self._matches_any(msg_l, CAPABILITY_DISCOVERY_PATTERNS):
            _push("capability_discovery")
            # No additional capability skills for a "what can you do"
            # question — keeps the answer focused on the inventory.
            return selected

        # 3. enabled capability skills whose intent_patterns (or extra
        #    keywords) match the user message.
        if cap_reg is not None:
            for cap in cap_reg.list_enabled():
                for sk in cap.skills:
                    if sk.status != "enabled":
                        continue
                    if self._skill_matches(msg_l, sk.skill_id, sk.intent_patterns):
                        _push(sk.skill_id)

        return selected

    def _matches_any(self, msg_l: str, patterns: Iterable[str]) -> bool:
        for p in patterns:
            if not p:
                continue
            p_l = p.lower()
            if p_l and p_l in msg_l:
                return True
        return False

    def _skill_matches(
        self,
        msg_l: str,
        skill_id: str,
        intent_patterns: Iterable[str],
    ) -> bool:
        if self._matches_any(msg_l, intent_patterns):
            return True
        extras = EXTRA_KEYWORDS.get(skill_id, [])
        if self._matches_any(msg_l, extras):
            return True
        return False


# ── Module-level convenience ──

def select_skills(
    user_message: str,
    capability_registry=None,
    *,
    base_skills: Optional[Iterable[str]] = None,
) -> List[str]:
    """Functional API: instantiate a default SkillSelector and select."""
    return SkillSelector(capability_registry).select(
        user_message,
        capability_registry=capability_registry,
        base_skills=base_skills,
    )
