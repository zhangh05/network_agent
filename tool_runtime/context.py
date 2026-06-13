# tool_runtime/context.py
"""ToolRuntimeContext — carries invocation context from caller through to ToolInvocation.

Provides a standard way for Module / Service layers to pass workspace, run, job,
caller identity, and already-validated approval information when invoking tools.

Example usage in a Module service:
    ctx = ToolRuntimeContext(
        workspace_id="default",
        run_id=run_id,
        module="config_translation",
        skill="config_translation",
        requested_by="module:config_translation",
        approval_id=approved_id,  # only after the caller has validated it
    )
    client = get_default_tool_runtime_client()
    result = client.invoke("parser.parse_config_text", {"config_text": cfg}, context=ctx)
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolRuntimeContext:
    """Standard context carried through tool invocations.

    All fields are optional — tools must work with partial context.
    None values mean "not set by caller" and are preserved as-is.
    """

    workspace_id: Optional[str] = None
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    job_id: Optional[str] = None
    capability: Optional[str] = None
    skill: Optional[str] = None
    module: Optional[str] = None
    requested_by: str = ""
    dry_run_default: bool = False
    approval_id: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "capability": self.capability,
            "skill": self.skill,
            "module": self.module,
            "requested_by": self.requested_by,
            "dry_run_default": self.dry_run_default,
            "approval_id": self.approval_id,
        }
