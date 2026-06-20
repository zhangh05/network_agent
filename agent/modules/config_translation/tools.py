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
  Compatibility fields (manual_review_count, source_count) are preserved
  at the top level for v0.7.x consumers (loop.py / trace recorder).
"""

from agent.tools.schemas import ToolSpec


TOOL_CONFIG_TRANSLATION = ToolSpec(
    tool_id="config.analysis.run",
    name="translate_config",
    category="config",
    description=(
        "Translate network device configuration between vendors using the "
        "config translation module. For uploaded files, pass filepath instead "
        "of copying the full file into source_config. Requires target_vendor "
        "and either filepath or source_config. "
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
                "description": "Short inline source configuration. Prefer filepath for uploaded files.",
            },
            "filepath": {
                "type": "string",
                "description": "Workspace-relative path to an uploaded configuration file.",
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
        "required": ["target_vendor"],
    },
    source="module:config_translation",
)


def tool_handler(args: dict, context=None) -> dict:
    """Handle config.analysis.run tool invocations.

    v0.8.2: returns a dict that is structurally a ToolResult.
    """
    from agent.modules.config_translation.service import translate_config, to_module_result
    from agent.protocol.tool_result import ToolResult

    source_config = args.get("source_config", "")
    filepath = args.get("filepath", "")
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

    try:
        source_config, source_error = _load_source_config(
            source_config=source_config,
            filepath=filepath,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        return {
            "ok": False,
            "status": "failed",
            "summary": f"无法读取源配置文件：{str(exc)[:160]}",
            "errors": [str(exc)[:200]],
        }
    if source_error:
        return {
            "ok": False,
            "status": "failed",
            "summary": source_error,
            "errors": ["source_file_error"],
        }

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
        tool_id="config.analysis.run",
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


def _load_source_config(source_config: str, filepath: str, workspace_id: str) -> tuple[str, str]:
    """Resolve inline or workspace-file input without exposing host paths."""
    if source_config and source_config.strip():
        return source_config, ""
    if not filepath:
        return "", "需要提供源配置文本或工作区文件路径。"

    from tool_runtime.path_security import safe_workspace_path

    target = safe_workspace_path(workspace_id, filepath)
    if not target.is_file():
        return "", f"源配置文件不存在：{filepath}"
    if target.stat().st_size > 1024 * 1024:
        return "", "源配置文件过大，当前最大支持 1MB。"
    with target.open("rb") as stream:
        if b"\x00" in stream.read(1024):
            return "", "源配置文件不是可读取的文本文件。"
    return target.read_text(encoding="utf-8", errors="replace"), ""
