# agent/runtime/durable/subagent.py
"""Phase 9: Subagent Runtime — isolated worker profiles, tasks, and execution."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
import uuid, time as _time

def _now(): return _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime())
def _sid(): return f"sub-{uuid.uuid4().hex[:8]}"

# ── Profiles ──

@dataclass
class SubagentProfile:
    profile_id: str
    name: str
    role: str = ""
    description: str = ""
    allowed_tools: list = field(default_factory=list)       # explicit tool_id list
    allowed_action_classes: list = field(default_factory=list)  # read/write/execute/...
    max_steps: int = 5
    max_runtime_seconds: int = 60
    max_context_tokens: int = 8000
    memory_write_policy: str = "pending_only"  # none | pending_only
    can_modify_files: bool = False
    can_execute_commands: bool = False
    can_call_network: bool = False
    output_contract: str = ""  # description of expected output format
    merge_strategy: str = "append"  # append | replace | report

BUILTIN_PROFILES: dict[str, SubagentProfile] = {
    "review_agent": SubagentProfile(
        profile_id="review_agent", name="Review Agent",
        role="Code/config reviewer — read-only, no modifications",
        allowed_action_classes=["read"],
        allowed_tools=["workspace.file.read", "workspace.file.list", "code.search",
                       "knowledge.search", "knowledge.read", "git.diff", "git.log",
                       "git.status", "tool.catalog.search"],
        max_steps=5, max_runtime_seconds=120,
        memory_write_policy="pending_only",
        output_contract="Review findings with severity: info/warning/critical",
    ),
    "fix_agent": SubagentProfile(
        profile_id="fix_agent", name="Fix Agent",
        role="Applies fixes to code/config — write access, approval required",
        allowed_action_classes=["read", "write"],
        allowed_tools=["workspace.file.read", "workspace.file.edit",
                       "workspace.file.list", "workspace.file.patch",
                       "workspace.file.write_artifact", "code.search",
                       "git.status", "git.diff", "exec.run"],
        max_steps=8, max_runtime_seconds=180,
        can_modify_files=True, can_execute_commands=True,
        memory_write_policy="pending_only",
        output_contract="List of changes made with before/after snippets",
    ),
    "test_agent": SubagentProfile(
        profile_id="test_agent", name="Test Agent",
        role="Runs tests and validations — limited execution",
        allowed_action_classes=["read", "execute"],
        allowed_tools=["exec.run", "exec.python", "workspace.file.read",
                       "workspace.file.list", "code.search", "system.diagnostics"],
        max_steps=5, max_runtime_seconds=120,
        can_execute_commands=True,
        memory_write_policy="none",
        output_contract="Test results: passed/failed counts, error details",
    ),
    "doc_agent": SubagentProfile(
        profile_id="doc_agent", name="Documentation Agent",
        role="Updates documentation files",
        allowed_action_classes=["read", "write"],
        allowed_tools=["workspace.file.read", "workspace.file.edit",
                       "workspace.file.list", "workspace.file.write_artifact",
                       "code.search", "document.safe_summary.render"],
        max_steps=5, max_runtime_seconds=120,
        can_modify_files=True,
        memory_write_policy="pending_only",
        output_contract="Updated doc files with change summary",
    ),
    "network_diag_agent": SubagentProfile(
        profile_id="network_diag_agent", name="Network Diagnostic Agent",
        role="Diagnoses network issues — read-only network access",
        allowed_action_classes=["read", "network"],
        allowed_tools=["device.list", "device.get", "system.diagnostics",
                       "knowledge.search", "knowledge.read", "pcap.analysis.run",
                       "web.search", "web.page.process"],
        max_steps=8, max_runtime_seconds=180,
        can_call_network=True,
        memory_write_policy="pending_only",
        output_contract="Diagnosis report with root cause and recommendations",
    ),
    "config_translate_agent": SubagentProfile(
        profile_id="config_translate_agent", name="Config Translation Agent",
        role="Translates network config between vendors",
        allowed_action_classes=["read", "write"],
        allowed_tools=["config.analysis.run", "workspace.file.read",
                       "workspace.file.edit", "workspace.file.write_artifact",
                       "knowledge.search", "knowledge.read"],
        max_steps=10, max_runtime_seconds=300,
        can_modify_files=True,
        memory_write_policy="pending_only",
        output_contract="Translated config with mapping table and warnings",
    ),
    "security_agent": SubagentProfile(
        profile_id="security_agent", name="Security Audit Agent",
        role="Reviews permissions, risks, and access patterns — read-only",
        allowed_action_classes=["read"],
        allowed_tools=["workspace.file.read", "workspace.file.list",
                       "code.search", "knowledge.search", "knowledge.read",
                       "tool.catalog.search", "system.review.item.list",
                       "memory.search"],
        max_steps=5, max_runtime_seconds=120,
        memory_write_policy="pending_only",
        output_contract="Security findings with risk levels and recommendations",
    ),
}


# ── SubagentTask & Result ──

@dataclass
class SubagentTask:
    subtask_id: str = field(default_factory=_sid)
    parent_task_id: str = ""
    workspace_id: str = ""
    session_id: str = ""
    profile_id: str = ""
    goal: str = ""
    input_context_refs: list = field(default_factory=list)
    status: str = "created"  # created | running | succeeded | failed | cancelled
    allowed_tools: list = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    created_at: str = ""
    finished_at: str = ""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now()


@dataclass
class SubagentResult:
    subtask_id: str = ""
    status: str = ""
    summary: str = ""
    findings: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    memory_candidates: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    finished_at: str = ""


# ── Runtime ──

def get_profile(profile_id: str) -> Optional[SubagentProfile]:
    return BUILTIN_PROFILES.get(profile_id)


def create_subagent_task(
    parent_task_id: str, workspace_id: str, session_id: str,
    profile_id: str, goal: str, context_refs: list = None,
) -> dict:
    profile = get_profile(profile_id)
    if not profile:
        return {"ok": False, "error": f"unknown profile: {profile_id}"}
    if not workspace_id:
        return {"ok": False, "error": "workspace_id required"}

    task = SubagentTask(
        parent_task_id=parent_task_id,
        workspace_id=workspace_id,
        session_id=session_id,
        profile_id=profile_id,
        goal=goal,
        input_context_refs=context_refs or [],
        allowed_tools=profile.allowed_tools,
        budget={"max_steps": profile.max_steps, "max_runtime_seconds": profile.max_runtime_seconds},
    )
    _save_task(task)

    _emit_event(workspace_id, parent_task_id, session_id, "subagent_created",
                f"Subagent {profile.name} created for task {parent_task_id}")

    return {"ok": True, "subtask_id": task.subtask_id, "profile": profile.name}


def run_subagent_task(subtask_id: str, ws_id: str) -> dict:
    task = _load_task(ws_id, subtask_id)
    if not task:
        return {"ok": False, "error": "subtask not found"}
    if task.workspace_id != ws_id:
        return {"ok": False, "error": "workspace mismatch"}

    profile = get_profile(task.profile_id)
    if not profile:
        return {"ok": False, "error": "profile not found"}

    task.status = "running"; _save_task(task)

    start = _time.time()
    elapsed = 0
    steps = 0

    result = SubagentResult(subtask_id=subtask_id, status="succeeded")

    try:
        # Simulate tool execution with profile constraints
        for tool_id in task.allowed_tools[:profile.max_steps]:
            if elapsed >= profile.max_runtime_seconds:
                result.warnings.append(f"Budget exceeded: {profile.max_runtime_seconds}s")
                result.status = "failed"
                break
            if steps >= profile.max_steps:
                result.warnings.append(f"Max steps exceeded: {profile.max_steps}")
                result.status = "failed"
                break

            # Profile action_class check
            m = _get_manifest(tool_id)
            if m and m.action_class not in profile.allowed_action_classes:
                result.status = "failed"
                result.errors.append(f"Tool {tool_id} action_class={m.action_class} not allowed for {profile.profile_id}")
                break

            # Caller=subagent execution through ToolRuntimeClient
            try:
                tresult = _execute_as_subagent(tool_id, {"goal": task.goal}, ws_id)
                result.tool_results.append({
                    "tool_id": tool_id, "ok": tresult.get("ok", True),
                    "summary": str(tresult.get("summary", ""))[:200],
                })
            except Exception as e:
                result.errors.append(f"{tool_id}: {str(e)[:200]}")

            steps += 1
            elapsed = _time.time() - start

        if steps > 0 and result.status == "succeeded":
            result.summary = f"Subagent {profile.name} completed {steps} tool calls"
            if result.tool_results:
                result.findings = [r["summary"] for r in result.tool_results if r["ok"]]

    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e)[:200])

    task.status = result.status
    task.finished_at = _now()
    _save_task(task)
    result.finished_at = _now()

    # Emit timeline events
    event_type = "subagent_succeeded" if result.status == "succeeded" else "subagent_failed"
    _emit_event(ws_id, task.parent_task_id, task.session_id, event_type,
                f"Subagent {profile.name}: {result.summary}")

    return {
        "ok": True,
        "subtask_id": subtask_id,
        "status": result.status,
        "summary": result.summary,
        "findings": result.findings,
        "tool_results": result.tool_results,
        "errors": result.errors,
        "warnings": result.warnings,
    }


def merge_subagent_result(parent_task_id: str, subtask_id: str, ws_id: str) -> dict:
    task = _load_task(ws_id, subtask_id)
    if not task:
        return {"ok": False, "error": "subtask not found"}
    if task.workspace_id != ws_id:
        return {"ok": False, "error": "workspace mismatch"}
    if task.parent_task_id != parent_task_id:
        return {"ok": False, "error": "subtask parent mismatch"}

    profile = get_profile(task.profile_id)
    _emit_event(ws_id, parent_task_id, task.session_id, "subagent_merged",
                f"Subagent {profile.name if profile else subtask_id} merged into parent")

    return {"ok": True, "merged": True, "subtask_id": subtask_id, "parent_task_id": parent_task_id}


# ── Helpers ──

def _save_task(task: SubagentTask):
    from workspace.run_store import WS_ROOT
    from workspace.atomic_io import atomic_write_json
    from dataclasses import asdict
    d = WS_ROOT / task.workspace_id / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / f"{task.subtask_id}.json", asdict(task))

def _load_task(ws_id: str, subtask_id: str) -> Optional[SubagentTask]:
    import json
    from workspace.run_store import WS_ROOT
    p = WS_ROOT / ws_id / "subagents" / f"{subtask_id}.json"
    if not p.exists(): return None
    try:
        raw = json.loads(p.read_text())
        return SubagentTask(**{k:v for k,v in raw.items() if k in SubagentTask.__dataclass_fields__})
    except: return None

def _get_manifest(tool_id: str):
    try:
        from tool_runtime.manifest_registry import get_manifest as gm
        return gm(tool_id)
    except: return None

def _execute_as_subagent(tool_id: str, args: dict, ws_id: str) -> dict:
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id=ws_id, requested_by="subagent")
        result = client.invoke(tool_id, args, context=ctx)
        return {"ok": result.status in ("succeeded", "dry_run"), "summary": result.summary or ""}
    except Exception as e:
        return {"ok": False, "summary": str(e)[:200]}

def _emit_event(ws_id: str, parent_task_id: str, session_id: str, event_type: str, summary: str):
    try:
        from agent.runtime.durable import RuntimeEvent
        from agent.runtime.durable.store import append_event
        append_event(RuntimeEvent(
            event_id=f"evt-sub-{uuid.uuid4().hex[:8]}",
            task_id=parent_task_id, workspace_id=ws_id,
            session_id=session_id, run_id="",
            type=event_type, status="ok",
            title=event_type, summary=summary[:200],
        ))
    except: pass
