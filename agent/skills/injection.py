# agent/skills/injection.py
"""SkillInjection — inject enabled skills into LLM context."""


def build_skill_injections(turn_context) -> str:
    """Build system prompt text describing current capabilities.

    v2.3.3: When the per-turn tool plan includes tools beyond base skills,
    inject a note that function-calling tools are available for this turn.
    This prevents the LLM from wrongly concluding it can only do chat
    when web/weather/host tools are in the catalog.
    """
    if turn_context and turn_context.skill_snapshot:
        snap = turn_context.skill_snapshot
    else:
        return ""

    lines = ["[CAPABILITIES]"]
    lines.append("You are a network agent with these capabilities:")

    enabled = snap.get("enabled", [])
    selected = []
    if turn_context:
        selected = list(getattr(turn_context, "metadata", {}).get("selected_skills", []) or [])
    if selected:
        selected_set = set(selected)
        enabled = [s for s in enabled if s.get("skill_id") in selected_set]
    if enabled:
        lines.append("")
        lines.append("CURRENT Capabilities (available THIS TURN):")
        for s in enabled:
            prompt = s.get("prompt_summary", s.get("name", ""))
            if prompt:
                lines.append(f"  - {prompt}")

    # v2.3.3: Signal that additional tools are available via function calling.
    # The tool catalog (web.search, web.weather.*, host.shell.*, etc.) is
    # sent as OpenAI-format function definitions. Without this note, the LLM
    # may wrongly assume only the capability-level skills are available.
    visible_tools = []
    if turn_context:
        visible_tools = list(getattr(turn_context, "metadata", {}).get("visible_tools", []) or [])
    if visible_tools:
        lines.append("")
        lines.append(f"ADDITIONAL TOOLS (available via function call this turn — {len(visible_tools)} tools):")
        for t in visible_tools[:12]:
            lines.append(f"  - {t}")
        if len(visible_tools) > 12:
            lines.append(f"  ... and {len(visible_tools) - 12} more")

    planned = snap.get("planned", [])
    if planned:
        lines.append("")
        lines.append("FUTURE Capabilities (NOT available yet — do NOT claim you can do these):")
        for s in planned:
            lines.append(f"  - {s.get('name', '')}")

    return "\n".join(lines)
