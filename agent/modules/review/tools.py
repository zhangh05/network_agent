# agent/modules/review/tools.py
"""Manual review flow tool handlers (v0.9).

v0.8.2 result-contract adapter pattern:
  service -> ModuleResult -> ToolResult -> dict (10 fields).

Strict contract:
  - Never modify the original translated_config content.
  - Never produce a deployable_config.
  - Stay on local host; no device pushing.
"""

from agent.tools.schemas import ToolSpec


TOOL_REVIEW_LIST = ToolSpec(
    tool_id="system.manage",
    name="list_items",
    category="review",
    description=(
        "List manual_review_items for an artifact with current status "
        "(pending / accepted / ignored / modified) and user_note."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "artifact_id": {"type": "string", "description": "Artifact id to review."},
        },
        "required": ["workspace_id", "artifact_id"],
    },
    source="module:review",
)


TOOL_REVIEW_UPDATE = ToolSpec(
    tool_id="system.manage",
    name="update_item",
    category="review",
    description=(
        "Update one manual_review_item's status and user_note in the "
        "sidecar JSON. Does NOT modify the original artifact content "
        "and does NOT produce a deployable_config."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "artifact_id": {"type": "string", "description": "Artifact id to review."},
            "item_id": {"type": "string", "description": "Review item id from list_items."},
            "status": {
                "type": "string",
                "description": "New review status: pending, accepted, ignored, or modified.",
                "enum": ["pending", "accepted", "ignored", "modified"],
            },
            "user_note": {"type": "string", "description": "Optional note explaining the decision."},
        },
        "required": ["workspace_id", "artifact_id", "item_id", "status"],
    },
    source="module:review",
)


def _build_handler(service_fn, tool_id_str: str):
    def _handler(args: dict, context=None) -> dict:
        from agent.modules.review.service import to_module_result
        from agent.protocol.tool_result import ToolResult
        call_id = ""
        if context:
            call_id = (getattr(context, "call_id", None)
                        or getattr(context, "tool_call_id", "")) or ""
        try:
            result = service_fn(
                **{k: v for k, v in args.items() if k in (
                    "workspace_id", "artifact_id", "item_id",
                    "status", "user_note",
                )},
            )
        except Exception as e:
            result = {
                "ok": False,
                "summary": f"review service raised: {e!r}",
                "errors": ["review_service_raised"],
            }
        mr = to_module_result(result)
        tr = ToolResult.from_module_result(
            tool_id=tool_id_str,
            call_id=call_id,
            module_result=mr,
        )
        out = tr.to_dict()
        if "status" in result:
            out["status"] = result["status"]
        if "item_id" in result:
            out["item_id"] = result["item_id"]
        return out
    return _handler


from agent.modules.review import service as _review_service


tool_handler_list = _build_handler(_review_service.list_review_items, "system.manage")
tool_handler_update = _build_handler(_review_service.update_review_item, "system.manage")
