# agent/modules/config_translation/tools.py
"""Config Translation tool — registers translate_config as a runtime tool.

This tool wraps the config_translation module service.
It does NOT connect to real devices. It does NOT push configuration.
It does NOT produce authoritative deployable_config without module validation.
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

    Called by ToolRegistry.dispatch().
    """
    from agent.modules.config_translation.service import translate_config

    source_config = args.get("source_config", "")
    source_vendor = args.get("source_vendor", "auto")
    target_vendor = args.get("target_vendor", "huawei")
    options = args.get("options")

    workspace_id = "default"
    session_id = ""
    if context:
        workspace_id = getattr(context, "workspace_id", workspace_id)
        session_id = getattr(context, "session_id", session_id)

    result = translate_config(
        source_config=source_config,
        source_vendor=source_vendor,
        target_vendor=target_vendor,
        options=options,
        workspace_id=workspace_id,
        session_id=session_id,
    )

    return {
        "ok": result["ok"],
        "summary": result.get("summary", ""),
        "content": {
            "translated_config": result.get("translated_config", ""),
            "manual_review_items": result.get("manual_review_items", []),
            "manual_review_count": result.get("manual_review_count", 0),
            "source_vendor": result.get("source_vendor", ""),
            "target_vendor": result.get("target_vendor", ""),
            "line_count": result.get("line_count", 0),
        },
        "artifacts": result.get("artifacts", []),
        "manual_review_count": result.get("manual_review_count", 0),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
        "metadata": result.get("metadata", {}),
    }
