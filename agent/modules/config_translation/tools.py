# agent/modules/config_translation/tools.py
"""Config Translation tool — registers translate_config as a runtime tool.

This tool wraps the config_translation module service.
It does NOT connect to real devices. It does NOT push configuration.
It does NOT produce authoritative deployable_config without module validation.

v0.8.2 result contract:
  tool_handler returns a dict that is **structurally a ToolResult**
  (call_id / tool_id / ok / summary / content / data / artifacts /
  source_count / manual_review_count / errors / warnings / metadata).
  Internally:
    translate_config(args) -> result dict
    -> service.to_module_result(result)         # business output
    -> ToolResult.from_module_result(...)        # runtime contract
  Legacy fields (manual_review_count, source_count) are preserved
  at the top level for v0.7.x consumers (loop.py / trace recorder).
"""

from agent.tools.schemas import ToolSpec


TOOL_CONFIG_TRANSLATION = ToolSpec(
    tool_id="config_translation.translate_config",
    name="translate_config",
    category="config",
    description=(
        "Translate network device configuration between vendors using the "
        "config translation module. Requires source_config and target_vendor. "
        "Does not directly produce an authoritative deployable_config without "
        "module validation."
    ),
    risk_level="medium",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "source_config": {
                "type": "string",
                "description": "Source network device configuration text to translate",
            },
            "source_vendor": {
                "type": "string",
                "description": "Source vendor (e.g., cisco, juniper, huawei, h3c, auto)",
            },
            "target_vendor": {
                "type": "string",
                "description": "Target vendor (e.g., huawei, cisco, juniper, h3c)",
            },
            "options": {
                "type": "object",
                "description": "Optional translation options",
            },
        },
        "required": ["source_config", "target_vendor"],
    },
    source="module:config_translation",
)


def tool_handler(args: dict, context=None) -> dict:
    """Handle config_translation.translate_config tool invocations.

    v0.8.2: returns a dict that is structurally a ToolResult.
    """
    from agent.modules.config_translation.service import translate_config, to_module_result
    from agent.protocol.tool_result import ToolResult

    source_config = args.get("source_config", "")
    source_vendor = args.get("source_vendor", "auto")
    target_vendor = args.get("target_vendor", "huawei")
    options = args.get("options")

    workspace_id = "default"
    session_id = ""
    call_id = ""
    if context:
        workspace_id = getattr(context, "workspace_id", workspace_id)
        session_id = getattr(context, "session_id", session_id)
        call_id = getattr(context, "call_id", call_id) or getattr(context, "tool_call_id", "")

    # 1. Service call
    result = translate_config(
        source_config=source_config,
        source_vendor=source_vendor,
        target_vendor=target_vendor,
        options=options,
        workspace_id=workspace_id,
        session_id=session_id,
    )

    # 2. Project to ModuleResult (business output contract)
    mr = to_module_result(result)

    # 3. Project to ToolResult (runtime / LLM contract)
    tr = ToolResult.from_module_result(
        tool_id="config_translation.translate_config",
        call_id=call_id,
        module_result=mr,
    )

    # 4. Return as a dict (the loop / registry expects a dict today)
    out = tr.to_dict()
    # Backward-compat top-level fields for v0.7.x consumers
    # that read manual_review_count / source_count directly from the
    # handler return value.
    out["manual_review_count"] = tr.manual_review_count
    out["source_count"] = tr.source_count
    return out
