# agent/modules/artifact/tools.py
"""Artifact management tool handlers (v0.9).

Each tool is a thin v0.8.2 result-contract adapter: it calls the
service, projects to ModuleResult, then to ToolResult (which becomes
the v0.8.2 standard 10-field dict the runtime / LLM consume).

Strict contract:
  - No real device access.
  - No config.push.
  - No authoritative deployable_config generation.
  - No fabrication.
"""

from agent.tools.schemas import ToolSpec


def _make_spec(name: str, tool_id: str, description: str, properties: dict, required: list,
                category: str = "artifact", risk_level: str = "low") -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        name=name,
        category=category,
        description=description,
        risk_level=risk_level,
        enabled=True,
        requires_approval=False,
        callable_by_llm=True,
        forbidden=False,
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        source="module:artifact",
    )


TOOL_ARTIFACT_LIST = _make_spec(
    name="list",
    tool_id="artifact.list",
    description=(
        "List artifacts in a workspace, optionally filtered by session or "
        "type. Returns sanitized records (no local file paths)."
    ),
    properties={
        "workspace_id": {"type": "string", "description": "Workspace id."},
        "session_id": {"type": "string", "description": "Optional session id."},
        "artifact_type": {"type": "string", "description": "Optional type filter."},
        "limit": {"type": "integer", "description": "Max records."},
    },
    required=["workspace_id"],
)


TOOL_ARTIFACT_READ = _make_spec(
    name="read",
    tool_id="artifact.read",
    description=(
        "Read an artifact's content + metadata. Returns ok=false when the "
        "artifact is missing or sensitivity gates deny access. "
        "translated_config artifacts keep authoritative=false / "
        "deployable_config=false."
    ),
    properties={
        "workspace_id": {"type": "string"},
        "artifact_id": {"type": "string"},
        "allow_sensitive": {"type": "boolean", "description": "Allow sensitive content."},
    },
    required=["workspace_id", "artifact_id"],
)


TOOL_ARTIFACT_DIFF = _make_spec(
    name="diff",
    tool_id="artifact.diff",
    description=(
        "Compute a unified text diff between two artifacts in the same "
        "workspace. Returns ok=false when either is missing."
    ),
    properties={
        "workspace_id": {"type": "string"},
        "left_artifact_id": {"type": "string"},
        "right_artifact_id": {"type": "string"},
        "max_lines": {"type": "integer", "description": "Cap diff to N lines."},
    },
    required=["workspace_id", "left_artifact_id", "right_artifact_id"],
)


TOOL_ARTIFACT_EXPORT = _make_spec(
    name="export",
    tool_id="artifact.export",
    description=(
        "Render an artifact as txt or md. Does NOT push to a real device "
        "and does NOT generate a deployable_config."
    ),
    properties={
        "workspace_id": {"type": "string"},
        "artifact_id": {"type": "string"},
        "format": {"type": "string", "enum": ["txt", "md"]},
    },
    required=["workspace_id", "artifact_id", "format"],
)


# ── v0.8.2 tool handlers ──

def _build_handler(service_fn, tool_id_str: str):
    def _handler(args: dict, context=None) -> dict:
        from agent.modules.artifact.service import to_module_result
        from agent.protocol.tool_result import ToolResult
        workspace_id = args.get("workspace_id", "")
        session_id = args.get("session_id", "")
        artifact_id = args.get("artifact_id", "")
        call_id = ""
        if context:
            call_id = (getattr(context, "call_id", None)
                        or getattr(context, "tool_call_id", "")) or ""
        try:
            result = service_fn(
                **{k: v for k, v in args.items() if k in (
                    "workspace_id", "session_id", "artifact_id",
                    "left_artifact_id", "right_artifact_id",
                    "artifact_type", "limit", "allow_sensitive",
                    "format", "max_lines",
                )},
            )
        except Exception as e:
            result = {
                "ok": False,
                "summary": f"artifact service raised: {e!r}",
                "errors": ["artifact_service_raised"],
            }
        mr = to_module_result(result)
        tr = ToolResult.from_module_result(
            tool_id=tool_id_str,
            call_id=call_id,
            module_result=mr,
        )
        out = tr.to_dict()
        out["authoritative"] = bool(result.get("authoritative", False))
        out["deployable_config"] = bool(result.get("deployable_config", False))
        return out
    return _handler


tool_handler_list = _build_handler(
    lambda **kw: __import__("agent.modules.artifact.service", fromlist=["list_artifacts_for_session"]).list_artifacts_for_session(**kw),
    "artifact.list",
)
tool_handler_read = _build_handler(
    lambda **kw: __import__("agent.modules.artifact.service", fromlist=["read_artifact"]).read_artifact(**kw),
    "artifact.read",
)
tool_handler_diff = _build_handler(
    lambda **kw: __import__("agent.modules.artifact.service", fromlist=["diff_artifacts"]).diff_artifacts(**kw),
    "artifact.diff",
)
tool_handler_export = _build_handler(
    lambda **kw: __import__("agent.modules.artifact.service", fromlist=["export_artifact"]).export_artifact(**kw),
    "artifact.export",
)
