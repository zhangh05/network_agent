# runtime/diagnostics.py
"""Runtime diagnostics — safe, read-only diagnostic information.

Collects component status, counts, and metadata without exposing secrets.
"""

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


@dataclass
class ComponentStatus:
    name: str = ""
    status: str = "ok"  # ok | warning | error | unavailable
    message: str = ""
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class DiagnosticReport:
    components: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "components": [c.as_dict() for c in self.components],
            "summary": self.summary,
        }


def get_diagnostics(workspace_id: str = "default") -> DiagnosticReport:
    """Collect diagnostic information for a workspace."""
    report = DiagnosticReport()
    components = []
    ws_dir = WS_ROOT / workspace_id

    # 1. Workspace
    if ws_dir.exists():
        components.append(ComponentStatus("workspace", "ok",
            f"Workspace '{workspace_id}' exists"))
    else:
        components.append(ComponentStatus("workspace", "error",
            f"Workspace '{workspace_id}' not found"))

    # 2. Registry
    try:
        from registry.loader import get_registry_status
        reg = get_registry_status()
        components.append(ComponentStatus("registry", "ok",
            f"{reg['module_count']} modules, {reg['skill_count']} skills, {reg['capability_count']} capabilities",
            {"enabled_modules": reg.get("enabled_modules", [])}))
    except Exception as e:
        components.append(ComponentStatus("registry", "error", f"Registry failed: {str(e)[:100]}"))

    # 3. Run stats
    runs_dir = ws_dir / "runs"
    if runs_dir.is_dir():
        try:
            count = len(list(runs_dir.iterdir()))
            components.append(ComponentStatus("runs", "ok", f"{count} run records",
                {"count": count}))
        except Exception:
            components.append(ComponentStatus("runs", "warning", "Cannot count runs"))
    else:
        components.append(ComponentStatus("runs", "ok", "No runs yet", {"count": 0}))

    # 4. Artifact stats
    art_dir = ws_dir / "artifacts"
    if art_dir.is_dir():
        try:
            count = len(list(art_dir.iterdir()))
            components.append(ComponentStatus("artifacts", "ok", f"{count} artifacts",
                {"count": count}))
        except Exception:
            components.append(ComponentStatus("artifacts", "warning", "Cannot count artifacts"))
    else:
        components.append(ComponentStatus("artifacts", "ok", "No artifacts", {"count": 0}))

    # 5. Job stats
    jobs_dir = ws_dir / "jobs"
    if jobs_dir.is_dir():
        try:
            count = len(list(jobs_dir.iterdir()))
            components.append(ComponentStatus("jobs", "ok", f"{count} jobs",
                {"count": count}))
        except Exception:
            components.append(ComponentStatus("jobs", "warning", "Cannot count jobs"))
    else:
        components.append(ComponentStatus("jobs", "ok", "No jobs", {"count": 0}))

    # 6. Agent runtime
    try:
        from agent.graph import get_runtime_status
        agent_status = get_runtime_status()
        components.append(ComponentStatus("agent", "ok",
            f"Runtime: {agent_status.get('agent_runtime', '?')}, "
            f"LangGraph: {agent_status.get('langgraph_available', False)}",
            {"runtime_mode": agent_status.get("agent_runtime", "")}))
    except Exception as e:
        components.append(ComponentStatus("agent", "error", str(e)[:100]))

    # 7. Tool Runtime
    try:
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()
        components.append(ComponentStatus("tool_runtime", "ok",
            f"{len(tools)} tools registered",
            {"tool_count": len(tools), "tools": [t["tool_id"] for t in tools]}))
    except Exception as e:
        components.append(ComponentStatus("tool_runtime", "warning", str(e)[:100]))

    # 8. LLM
    try:
        from agent.llm.runtime import get_llm_status
        llm = get_llm_status()
        components.append(ComponentStatus("llm", "ok",
            f"Enabled: {llm.get('enabled')}, Provider: {llm.get('provider', 'disabled')}",
            {"enabled": llm.get("enabled"), "provider": llm.get("provider", "disabled"),
             "safe_mode": llm.get("safe_mode", True)}))
    except Exception as e:
        components.append(ComponentStatus("llm", "warning", str(e)[:100]))

    # 9. Memory
    try:
        from backend.api.memory import handle_memory_status
        components.append(ComponentStatus("memory", "ok", "Memory system available"))
    except Exception:
        components.append(ComponentStatus("memory", "warning", "Memory status unavailable"))

    report.components = components
    report.summary = {
        "total": len(components),
        "ok": sum(1 for c in components if c.status == "ok"),
        "warning": sum(1 for c in components if c.status == "warning"),
        "error": sum(1 for c in components if c.status == "error"),
    }
    return report
