# tool_runtime/manifest_registry.py
"""All tool manifests — single source of truth."""

from .manifest import CapabilityManifest, RetryPolicy

MANIFESTS: dict[str, CapabilityManifest] = {
    # ═══ browser ═══
    "browser.navigate": CapabilityManifest(
        tool_id="browser.navigate", category="browser", display_name="Browser Navigate",
        description="Navigate browser to a URL", action_class="network",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30, output_sensitivity="internal",
    ),
    "browser.screenshot": CapabilityManifest(
        tool_id="browser.screenshot", category="browser", display_name="Browser Screenshot",
        description="Capture page screenshot", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        output_sensitivity="sensitive", timeout_seconds=30,
    ),
    "browser.click": CapabilityManifest(
        tool_id="browser.click", category="browser", display_name="Browser Click",
        description="Click element on page", action_class="write",
        risk_level="low", side_effects="write", idempotency="unknown",
        timeout_seconds=20,
    ),
    "browser.extract": CapabilityManifest(
        tool_id="browser.extract", category="browser", display_name="Browser Extract",
        description="Extract page content", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ exec ═══
    "exec.run": CapabilityManifest(
        tool_id="exec.run", category="exec", display_name="Shell Execute",
        description="Execute shell command", action_class="execute",
        risk_level="medium", side_effects="remote_exec",
        idempotency="unsafe_to_retry", rollback_strategy="none",
        secret_fields=["cmd"], output_sensitivity="secret",
        timeout_seconds=120,
        approval_reason_template="Shell command execution: requires confirmation for destructive patterns",
    ),
    "exec.python": CapabilityManifest(
        tool_id="exec.python", category="exec", display_name="Python Execute",
        description="Execute Python code", action_class="execute",
        risk_level="medium", side_effects="remote_exec",
        idempotency="unsafe_to_retry",
        secret_fields=["code"], output_sensitivity="sensitive",
        timeout_seconds=60,
    ),
    "exec.slash": CapabilityManifest(
        tool_id="exec.slash", category="exec", display_name="Shell Command (direct)",
        description="Direct shell command", action_class="execute",
        risk_level="medium", side_effects="remote_exec",
        idempotency="unsafe_to_retry",
        output_sensitivity="sensitive", timeout_seconds=120,
    ),

    # ═══ file / workspace ═══
    "file.import_workspace_path": CapabilityManifest(
        tool_id="file.import_workspace_path", category="workspace", display_name="Import File",
        description="Import a file into workspace", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        timeout_seconds=30,
    ),
    "file.references": CapabilityManifest(
        tool_id="file.references", category="workspace", display_name="File References",
        description="List file references", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),

    # ═══ workspace ═══
    "workspace.artifact.delete_soft": CapabilityManifest(
        tool_id="workspace.artifact.delete_soft", category="workspace", display_name="Delete Artifact",
        description="Soft-delete an artifact", action_class="delete",
        risk_level="medium", requires_approval=True, destructive=True,
        side_effects="delete", idempotency="safe_to_retry",
        rollback_strategy="soft_delete_restore",
        approval_reason_template="Deleting artifact: requires confirmation",
        timeout_seconds=10,
    ),
    "workspace.artifact.diff": CapabilityManifest(
        tool_id="workspace.artifact.diff", category="workspace", display_name="Artifact Diff",
        description="Diff two artifact versions", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "workspace.artifact.list": CapabilityManifest(
        tool_id="workspace.artifact.list", category="workspace", display_name="List Artifacts",
        description="List workspace artifacts", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry", timeout_seconds=20,
    ),
    "workspace.artifact.read": CapabilityManifest(
        tool_id="workspace.artifact.read", category="workspace", display_name="Read Artifact",
        description="Read artifact content", action_class="read",
        risk_level="low", reads_artifact=True, side_effects="none",
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "workspace.artifact.save": CapabilityManifest(
        tool_id="workspace.artifact.save", category="workspace", display_name="Save Artifact",
        description="Save artifact to workspace", action_class="write",
        risk_level="low", writes_artifact=True, side_effects="write",
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "workspace.artifact.export": CapabilityManifest(
        tool_id="workspace.artifact.export", category="workspace", display_name="Export Artifact",
        description="Export artifact as file", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry", timeout_seconds=60,
    ),
    "workspace.artifact.tag": CapabilityManifest(
        tool_id="workspace.artifact.tag", category="workspace", display_name="Tag Artifact",
        description="Tag an artifact", action_class="write",
        risk_level="low", side_effects="write", idempotency="safe_to_retry", timeout_seconds=10,
    ),
    "workspace.file.list": CapabilityManifest(
        tool_id="workspace.file.list", category="workspace", display_name="List Files",
        description="List workspace files", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry", timeout_seconds=20,
    ),
    "workspace.file.read": CapabilityManifest(
        tool_id="workspace.file.read", category="workspace", display_name="Read File",
        description="Read file content", action_class="read",
        risk_level="low", reads_artifact=True, side_effects="none",
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "workspace.file.read_image": CapabilityManifest(
        tool_id="workspace.file.read_image", category="workspace", display_name="Read Image",
        description="Read image file", action_class="read",
        risk_level="low", reads_artifact=True, side_effects="none",
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "workspace.file.edit": CapabilityManifest(
        tool_id="workspace.file.edit", category="workspace", display_name="Edit File",
        description="Edit workspace file", action_class="write",
        risk_level="medium", side_effects="write", writes_artifact=True,
        idempotency="unsafe_to_retry", timeout_seconds=30,
    ),
    "workspace.file.patch": CapabilityManifest(
        tool_id="workspace.file.patch", category="workspace", display_name="Patch File",
        description="Apply patch to file", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unsafe_to_retry",
        timeout_seconds=30,
    ),
    "workspace.file.write_artifact": CapabilityManifest(
        tool_id="workspace.file.write_artifact", category="workspace", display_name="Write Artifact",
        description="Write file artifact", action_class="write",
        risk_level="low", writes_artifact=True, side_effects="write",
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "workspace.document.pdf.extract_text": CapabilityManifest(
        tool_id="workspace.document.pdf.extract_text", category="workspace", display_name="PDF Extract",
        description="Extract text from PDF", action_class="read",
        risk_level="low", reads_artifact=True, side_effects="none",
        idempotency="safe_to_retry", timeout_seconds=60,
    ),
    "workspace.metadata.get": CapabilityManifest(
        tool_id="workspace.metadata.get", category="workspace", display_name="Workspace Metadata",
        description="Get workspace metadata", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry", timeout_seconds=10,
    ),

    # ═══ git ═══
    "git.commit": CapabilityManifest(
        tool_id="git.commit", category="git", display_name="Git Commit",
        description="Commit changes", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unsafe_to_retry",
        requires_approval=True, approval_reason_template="Git commit: verify changes before committing",
        timeout_seconds=30,
    ),
    "git.push": CapabilityManifest(
        tool_id="git.push", category="git", display_name="Git Push",
        description="Push to remote", action_class="network",
        risk_level="high", requires_approval=True,
        side_effects="network_change", idempotency="unsafe_to_retry",
        approval_reason_template="Git push: confirm remote push is intentional",
        timeout_seconds=60,
    ),
    "git.diff": CapabilityManifest(
        tool_id="git.diff", category="git", display_name="Git Diff",
        description="Show working tree diff", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "git.log": CapabilityManifest(
        tool_id="git.log", category="git", display_name="Git Log",
        description="Show commit history", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "git.status": CapabilityManifest(
        tool_id="git.status", category="git", display_name="Git Status",
        description="Show working tree status", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),

    # ═══ code ═══
    "code.search": CapabilityManifest(
        tool_id="code.search", category="code", display_name="Code Search",
        description="Search codebase", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ data ═══
    "data.csv.summarize": CapabilityManifest(
        tool_id="data.csv.summarize", category="data", display_name="CSV Summarize",
        description="Summarize CSV data", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "data.table.extract": CapabilityManifest(
        tool_id="data.table.extract", category="data", display_name="Table Extract",
        description="Extract table from document", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "data.table.render": CapabilityManifest(
        tool_id="data.table.render", category="data", display_name="Table Render",
        description="Render table output", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "data.validate": CapabilityManifest(
        tool_id="data.validate", category="data", display_name="Data Validate",
        description="Validate data format/structure", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ diagram ═══
    "diagram.mermaid.render": CapabilityManifest(
        tool_id="diagram.mermaid.render", category="visualization", display_name="Mermaid Render",
        description="Render Mermaid diagram", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30, output_sensitivity="internal",
    ),

    # ═══ document ═══
    "document.safe_summary.render": CapabilityManifest(
        tool_id="document.safe_summary.render", category="document", display_name="Document Summary",
        description="Render safe document summary", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ text ═══
    "text.analyze": CapabilityManifest(
        tool_id="text.analyze", category="text", display_name="Text Analyze",
        description="Analyze text content", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ web ═══
    "web.search": CapabilityManifest(
        tool_id="web.search", category="web", display_name="Web Search",
        description="Search the web", action_class="network",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),
    "web.page.process": CapabilityManifest(
        tool_id="web.page.process", category="web", display_name="Web Page Process",
        description="Fetch and process web page", action_class="network",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=90,
    ),
    "web.weather": CapabilityManifest(
        tool_id="web.weather", category="web", display_name="Weather",
        description="Get weather data", action_class="network",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ knowledge ═══
    "knowledge.search": CapabilityManifest(
        tool_id="knowledge.search", category="knowledge", display_name="Knowledge Search",
        description="Search knowledge base", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "knowledge.read": CapabilityManifest(
        tool_id="knowledge.read", category="knowledge", display_name="Knowledge Read",
        description="Read knowledge entry", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "knowledge.import": CapabilityManifest(
        tool_id="knowledge.import", category="knowledge", display_name="Knowledge Import",
        description="Import knowledge entries", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        timeout_seconds=60,
    ),
    "knowledge.chunk.list": CapabilityManifest(
        tool_id="knowledge.chunk.list", category="knowledge", display_name="List Chunks",
        description="List knowledge chunks", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "knowledge.not_found.explain": CapabilityManifest(
        tool_id="knowledge.not_found.explain", category="knowledge", display_name="Explain Not Found",
        description="Explain why knowledge not found", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "knowledge.source.list": CapabilityManifest(
        tool_id="knowledge.source.list", category="knowledge", display_name="List Sources",
        description="List knowledge sources", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "knowledge.source.manage": CapabilityManifest(
        tool_id="knowledge.source.manage", category="knowledge", display_name="Manage Sources",
        description="Manage knowledge sources", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        timeout_seconds=30,
    ),
    "knowledge.source.reindex": CapabilityManifest(
        tool_id="knowledge.source.reindex", category="knowledge", display_name="Reindex Sources",
        description="Reindex knowledge sources", action_class="admin",
        risk_level="medium", side_effects="write", idempotency="safe_to_retry",
        timeout_seconds=300,
    ),

    # ═══ memory ═══
    "memory.search": CapabilityManifest(
        tool_id="memory.search", category="memory", display_name="Memory Search",
        description="Search agent memory", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        output_sensitivity="sensitive", timeout_seconds=30,
    ),
    "memory.manage": CapabilityManifest(
        tool_id="memory.manage", category="memory", display_name="Memory Manage",
        description="Manage memory entries", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        output_sensitivity="sensitive", timeout_seconds=30,
    ),
    "memory.profile": CapabilityManifest(
        tool_id="memory.profile", category="memory", display_name="Memory Profile",
        description="Get memory profile", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        output_sensitivity="sensitive", timeout_seconds=20,
    ),

    # ═══ device ═══
    "device.list": CapabilityManifest(
        tool_id="device.list", category="device", display_name="List Devices",
        description="List managed devices", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "device.get": CapabilityManifest(
        tool_id="device.get", category="device", display_name="Get Device",
        description="Get device details", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "device.add": CapabilityManifest(
        tool_id="device.add", category="device", display_name="Add Device",
        description="Add a managed device", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unsafe_to_retry",
        timeout_seconds=30,
    ),
    "device.delete": CapabilityManifest(
        tool_id="device.delete", category="device", display_name="Delete Device",
        description="Delete a managed device", action_class="delete",
        risk_level="high", requires_approval=True, destructive=True,
        side_effects="delete", idempotency="unsafe_to_retry",
        approval_reason_template="Deleting device: irreversible operation, confirm before proceeding",
        timeout_seconds=20,
    ),

    # ═══ agent ═══
    "agent.result.get": CapabilityManifest(
        tool_id="agent.result.get", category="agent", display_name="Get Result",
        description="Get agent execution result", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "agent.role.list": CapabilityManifest(
        tool_id="agent.role.list", category="agent", display_name="List Roles",
        description="List agent roles", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=10,
    ),
    "agent.spawn": CapabilityManifest(
        tool_id="agent.spawn", category="agent", display_name="Spawn Agent",
        description="Spawn a subagent", action_class="admin",
        risk_level="high", requires_approval=True,
        side_effects="remote_exec", idempotency="unsafe_to_retry",
        approval_reason_template="Spawning subagent: verify scope and permissions",
        timeout_seconds=60,
    ),
    "agent.team.run": CapabilityManifest(
        tool_id="agent.team.run", category="agent", display_name="Team Run",
        description="Run agent team coordination", action_class="admin",
        risk_level="high", requires_approval=True,
        side_effects="remote_exec", idempotency="unsafe_to_retry",
        approval_reason_template="Running agent team: confirm team composition and permissions",
        timeout_seconds=300,
    ),

    # ═══ config ═══
    "config.analysis.run": CapabilityManifest(
        tool_id="config.analysis.run", category="config", display_name="Config Analysis",
        description="Analyze network config", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),

    # ═══ report ═══
    "report.artifact.save": CapabilityManifest(
        tool_id="report.artifact.save", category="report", display_name="Save Report",
        description="Save report as artifact", action_class="write",
        risk_level="low", side_effects="write", writes_artifact=True,
        idempotency="safe_to_retry", timeout_seconds=30,
    ),
    "report.markdown.render": CapabilityManifest(
        tool_id="report.markdown.render", category="report", display_name="Render Markdown",
        description="Render Markdown report", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ system ═══
    "system.diagnostics": CapabilityManifest(
        tool_id="system.diagnostics", category="system", display_name="System Diagnostics",
        description="Run system diagnostics", action_class="admin",
        risk_level="medium", side_effects="read", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),
    "system.review.item.list": CapabilityManifest(
        tool_id="system.review.item.list", category="system", display_name="Review Items",
        description="List review items", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "system.review.item.update": CapabilityManifest(
        tool_id="system.review.item.update", category="system", display_name="Update Review",
        description="Update review item", action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        timeout_seconds=20,
    ),
    "system.run.get": CapabilityManifest(
        tool_id="system.run.get", category="system", display_name="Get Run",
        description="Get run details", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "system.session.get": CapabilityManifest(
        tool_id="system.session.get", category="system", display_name="Get Session",
        description="Get session details", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
    "system.session.checkpoint": CapabilityManifest(
        tool_id="system.session.checkpoint", category="system", display_name="Session Checkpoint",
        description="Create session checkpoint", action_class="admin",
        risk_level="medium", side_effects="write", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),
    "system.session.export": CapabilityManifest(
        tool_id="system.session.export", category="system", display_name="Session Export",
        description="Export session data", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),
    "system.session.rewind": CapabilityManifest(
        tool_id="system.session.rewind", category="system", display_name="Session Rewind",
        description="Rewind session state", action_class="admin",
        risk_level="high", requires_approval=True, destructive=True,
        side_effects="delete", idempotency="unsafe_to_retry",
        approval_reason_template="Rewinding session: will discard recent state",
        timeout_seconds=30,
    ),
    "system.session.snapshot": CapabilityManifest(
        tool_id="system.session.snapshot", category="system", display_name="Session Snapshot",
        description="Take session snapshot", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ pcap ═══
    "pcap.analysis.run": CapabilityManifest(
        tool_id="pcap.analysis.run", category="network", display_name="PCAP Analysis",
        description="Analyze packet capture", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),

    # ═══ tool ═══
    "tool.catalog.search": CapabilityManifest(
        tool_id="tool.catalog.search", category="tooling", display_name="Tool Search",
        description="Search tool catalog", action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),
}

def get_manifest(tool_id: str) -> CapabilityManifest | None:
    return MANIFESTS.get(tool_id)

def get_all_manifests() -> dict[str, CapabilityManifest]:
    return dict(MANIFESTS)

def validate_all() -> tuple[list[str], int]:
    """Validate all manifests. Returns (errors, count)."""
    errors = []
    for tid, m in MANIFESTS.items():
        errs = m.validate()
        for e in errs:
            errors.append(f"[{tid}] {e}")
    return errors, len(MANIFESTS)

def is_retryable(tool_id: str) -> bool:
    m = MANIFESTS.get(tool_id)
    if not m: return False
    if m.destructive: return False
    return m.idempotency == "safe_to_retry"
