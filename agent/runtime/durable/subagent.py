# agent/runtime/durable/subagent.py
"""Phase 9: Subagent Runtime — isolated worker profiles, tasks, and execution."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
import uuid, time as _time
from agent.runtime.utils import now_iso

# ── Re-export for convenience ──
# All 7 profiles are the single source of truth for subagent types.
# The frontend and tool layer reference these IDs directly.

def _now(): return now_iso()
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
        allowed_tools=["workspace.file", "workspace.artifact", "code.search",
                       "knowledge.manage", "git.manage",
                       "web.manage"],
        max_steps=5, max_runtime_seconds=120,
        memory_write_policy="pending_only",
        output_contract="Review findings with severity: info/warning/critical",
    ),
    "fix_agent": SubagentProfile(
        profile_id="fix_agent", name="Fix Agent",
        role="Applies fixes to code/config — write access, approval required",
        allowed_action_classes=["read", "write"],
        allowed_tools=["workspace.file", "workspace.artifact",
                       "code.search",
                       "git.manage", "exec.run"],
        max_steps=8, max_runtime_seconds=180,
        can_modify_files=True, can_execute_commands=True,
        memory_write_policy="pending_only",
        output_contract="List of changes made with before/after snippets",
    ),
    "test_agent": SubagentProfile(
        profile_id="test_agent", name="Test Agent",
        role="Runs tests and validations — limited execution",
        allowed_action_classes=["read", "execute"],
        allowed_tools=["exec.run", "workspace.file",
                       "code.search", "system.manage"],
        max_steps=5, max_runtime_seconds=120,
        can_execute_commands=True,
        memory_write_policy="none",
        output_contract="Test results: passed/failed counts, error details",
    ),
    "doc_agent": SubagentProfile(
        profile_id="doc_agent", name="Documentation Agent",
        role="Updates documentation files",
        allowed_action_classes=["read", "write"],
        allowed_tools=["workspace.file", "workspace.artifact",
                       "code.search", "report.manage"],
        max_steps=5, max_runtime_seconds=120,
        can_modify_files=True,
        memory_write_policy="pending_only",
        output_contract="Updated doc files with change summary",
    ),
    "network_diag_agent": SubagentProfile(
        profile_id="network_diag_agent", name="Network Diagnostic Agent",
        role="Diagnoses network issues — read-only network access",
        allowed_action_classes=["read", "network"],
        allowed_tools=["device.manage", "system.manage",
                       "knowledge.manage", "pcap.manage",
                       "web.manage"],
        max_steps=8, max_runtime_seconds=180,
        can_call_network=True,
        memory_write_policy="pending_only",
        output_contract="Diagnosis report with root cause and recommendations",
    ),
    "config_translate_agent": SubagentProfile(
        profile_id="config_translate_agent", name="Config Translation Agent",
        role="Translates network config between vendors",
        allowed_action_classes=["read", "write"],
        allowed_tools=["config.manage", "workspace.file", "workspace.artifact",
                       "knowledge.manage"],
        max_steps=10, max_runtime_seconds=300,
        can_modify_files=True,
        memory_write_policy="pending_only",
        output_contract="Translated config with mapping table and warnings",
    ),
    "security_agent": SubagentProfile(
        profile_id="security_agent", name="Security Audit Agent",
        role="Reviews permissions, risks, and access patterns — read-only",
        allowed_action_classes=["read"],
        allowed_tools=["workspace.file", "workspace.artifact",
                       "code.search", "knowledge.manage",
                       "system.manage", "memory.manage"],
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
    """Real LLM-driven subagent execution through SSOT Runtime.

    The profile provides the SSOT Runtime-visible tool allowlist. Tool execution still
    goes through ToolRuntimeClient with caller=subagent.
    """
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
    result = SubagentResult(subtask_id=subtask_id, status="succeeded")

    # Register in live tasks registry for cancel/status
    from agent.runtime.durable.trajectory import _live_tasks
    _live_tasks[subtask_id] = {
        "subtask_id": subtask_id,
        "status": "running",
        "profile_id": task.profile_id,
        "goal": task.goal,
        "started_at": _now(),
    }

    try:
        # Create restricted session for profile-gated SSOT Runtime execution.
        from agent.core.session import AgentSession

        child_session_id = subtask_id
        sess = AgentSession(session_id=child_session_id, workspace_id=ws_id)
        sess.mark_sub_agent()
        sess.metadata["max_steps"] = profile.max_steps
        sess.metadata["parent_session_id"] = task.session_id
        sess.metadata["subtask_id"] = subtask_id

        # Submit via SSOT Runtime with restricted tools.
        from agent.core.turn import AgentTurn
        from agent.protocol.op import AgentOp
        from agent.runtime.ssot_runtime import run_ssot_turn
        op = AgentOp(
            user_input=task.goal,
            workspace_id=ws_id,
            session_id=child_session_id,
            metadata={
                "subagent_profile": {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "role": profile.role,
                    "max_steps": profile.max_steps,
                    "max_runtime_seconds": profile.max_runtime_seconds,
                    "allowed_action_classes": list(profile.allowed_action_classes),
                    "output_contract": profile.output_contract,
                },
                "parent_session_id": task.session_id,
                "subtask_id": subtask_id,
            },
        )
        turn = AgentTurn.from_op(op)
        turn.metadata = {
            "max_steps": profile.max_steps,
            "subtask_id": subtask_id,
            "subagent_profile": profile.profile_id,
        }

        try:
            llm_result = _run_ssot_runtime_with_timeout(
                run_ssot_turn,
                sess,
                turn,
                set(profile.allowed_tools or []),
                timeout_seconds=profile.max_runtime_seconds,
            )
        except Exception as e:
            raise RuntimeError(f"LLM turn failed: {str(e)[:200]}") from e

        elapsed = _time.time() - start
        final_resp = getattr(llm_result, 'final_response', '') or ''
        is_ok = getattr(llm_result, 'ok', False)

        # AgentResult.tool_calls is the canonical one-row-per-action projection.
        for te in (getattr(llm_result, "tool_calls", []) or []):
            te_get = te.get if isinstance(te, dict) else lambda key, default=None: getattr(te, key, default)
            tool_id = str(te_get("tool_id", "") or "")
            tools_ok = bool(te_get("ok", False))
            summary = str(te_get("summary", "") or "")[:200]
            result.tool_results.append({
                "tool_id": tool_id, "ok": tools_ok,
                "summary": summary,
            })

        if is_ok and final_resp:
            result.summary = final_resp[:4000]
            result.findings = [final_resp[:1000]]
        elif elapsed >= profile.max_runtime_seconds:
            result.status = "failed"
            result.warnings.append(f"Budget exceeded: {profile.max_runtime_seconds}s")
            result.summary = "Subagent timed out"
        else:
            result.status = "failed"
            result.summary = "Subagent LLM call failed"
            if not is_ok:
                result.errors.append("LLM returned error")

    except Exception as e:
        result.status = "failed"
        result.errors.append(f"subagent execution failed: {str(e)[:200]}")
        result.summary = f"Subagent execution error: {str(e)[:100]}"

    elapsed = _time.time() - start
    if elapsed >= profile.max_runtime_seconds:
        result.warnings.append(f"Runtime budget {profile.max_runtime_seconds}s exceeded")
        if result.status != "failed":
            result.status = "failed"

    task.status = result.status
    task.finished_at = _now()
    _save_task(task)
    result.finished_at = _now()

    # Update live tasks registry with final status
    from agent.runtime.durable.trajectory import _live_tasks
    if subtask_id in _live_tasks:
        _live_tasks[subtask_id]["status"] = result.status
        _live_tasks[subtask_id]["finished_at"] = _now()
        _live_tasks[subtask_id]["summary"] = (result.summary or "")[:200]

    # Emit timeline events
    event_type = "subagent_succeeded" if result.status == "succeeded" else "subagent_failed"
    _emit_event(ws_id, task.parent_task_id, task.session_id, event_type,
                f"Subagent {profile.name}: {result.summary[:200]}")

    # v3.10: Generate pending memory candidates (subagent cannot write active memory)
    try:
        from workspace.memory_governance import MemoryRecord, MemoryWriteGate
        gate = MemoryWriteGate()
        for tr in result.tool_results:
            if tr.get("ok"):
                rec = MemoryRecord(
                    workspace_id=ws_id, session_id=task.session_id,
                    task_id=task.parent_task_id, scope="task",
                    memory_type="tool_learning",
                    status="pending", source="subagent",
                    content=str(tr.get("summary", ""))[:500],
                    summary=f"Subagent {profile.name}: {tr.get('tool_id', '')}",
                    confidence=0.5,
                    citations=[{"subtask_id": subtask_id}],
                    created_by="subagent",
                    redacted=True,
                )
                gate.write(rec)
    except Exception as e:
        result.warnings.append(f"Memory candidate write failed: {str(e)[:100]}")

    return {
        "ok": result.status == "succeeded",
        "subtask_id": subtask_id,
        "child_session_id": subtask_id,
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
    except Exception: return None

def _get_manifest(tool_id: str):
    try:
        from core.tools.manifest_registry import get_manifest as gm
        return gm(tool_id)
    except Exception: return None

def _execute_as_subagent(tool_id: str, args: dict, ws_id: str) -> dict:
    try:
        from core.tools.integration import get_default_tool_runtime_client
        from core.tools.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id=ws_id, requested_by="subagent")
        result = client.invoke(tool_id, args, context=ctx)
        return {"ok": result.status in ("succeeded", "dry_run"), "summary": result.summary or ""}
    except Exception as e:
        return {"ok": False, "summary": str(e)[:200]}


def _run_ssot_runtime_with_timeout(run_fn, session, turn, allowed_tool_ids, *, timeout_seconds: int):
    """Run a subagent turn with a hard parent-side timeout.

    Python cannot forcibly stop an already-running provider call, so timeout
    returns control to the parent and marks the subtask failed while the worker
    thread is abandoned best-effort.
    """
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="subagent")
    future = executor.submit(
        run_fn,
        session,
        turn,
        None,
        allowed_tool_ids=allowed_tool_ids,
        requested_by="subagent",
    )
    try:
        return future.result(timeout=max(1, int(timeout_seconds)))
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"subagent runtime exceeded {timeout_seconds}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

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
    except Exception as e:
        # best-effort: event emission failure is logged, not propagated
        import logging
        logging.getLogger(__name__).debug("subagent event emission failed", exc_info=True)
