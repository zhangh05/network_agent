# agent/skills/injection.py
"""SkillInjection — inject enabled skills into LLM context."""


def build_skill_injections(turn_context) -> str:
    """Build system prompt text describing current capabilities."""
    if turn_context and turn_context.skill_snapshot:
        snap = turn_context.skill_snapshot
    else:
        return ""

    lines = ["[CAPABILITIES]"]
    lines.append("You are a network agent with these capabilities:")

    enabled = snap.get("enabled", [])
    if enabled:
        lines.append("")
        lines.append("CURRENT Capabilities (available NOW):")
        for s in enabled:
            prompt = s.get("prompt_summary", s.get("name", ""))
            if prompt:
                lines.append(f"  - {prompt}")

    planned = snap.get("planned", [])
    if planned:
        lines.append("")
        lines.append("FUTURE Capabilities (NOT available yet — do NOT claim you can do these):")
        for s in planned:
            lines.append(f"  - {s.get('name', '')}")

    return "\n".join(lines)
