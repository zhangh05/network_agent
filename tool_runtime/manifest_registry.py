# tool_runtime/manifest_registry.py
"""All tool manifests — single source of truth for the 21 canonical tools.

Each merged tool carries a base risk profile. Per-action destructive
checks in ``tool_runtime.policy`` escalate delete/rewind/destructive
commands to high risk and approval.
"""

from .manifest import CapabilityManifest, RetryPolicy

MANIFESTS: dict[str, CapabilityManifest] = {
    # ═══ 1. exec.run (merged: shell + python + slash) ═══
    "exec.run": CapabilityManifest(
        tool_id="exec.run", category="exec", display_name="Shell / Python / Slash",
        description=(
            "Unified exec tool. action=shell (default; target=local|ssh|telnet), "
            "use asset_id for saved devices so credentials stay server-side. "
            "action=python (AST-sandboxed), action=slash (registered slash command). "
            "Per-command approval triggered by RiskPolicy for dangerous patterns."
        ),
        action_class="execute",
        risk_level="medium",  # base level; dangerous patterns escalate to critical
        side_effects="remote_exec",
        idempotency="unsafe_to_retry", rollback_strategy="none",
        secret_fields=["cmd", "code"], output_sensitivity="secret",
        timeout_seconds=120,
    ),

    # ═══ 2. git.manage (merged: status+log+diff+commit+push) ═══
    "git.manage": CapabilityManifest(
        tool_id="git.manage", category="git", display_name="Git (unified)",
        description=(
            "Unified git tool. action=status, log, diff (reads); "
            "action=commit, push (writes, dispatcher enforces approval). "
            "Run status+diff first; never commit/push without confirmation."
        ),
        action_class="write",
        risk_level="medium",  # base level; commit/push escalate via dispatcher
        side_effects="network_change", idempotency="unsafe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ 3. device.manage (merged: list+get+add+delete) ═══
    "device.manage": CapabilityManifest(
        tool_id="device.manage", category="device", display_name="Device Asset (unified)",
        description=(
            "Unified CMDB tool. action=list, get (reads); "
            "action=add, update (writes); action=delete (destructive approval). "
            "Do not fabricate assets; do not expose credentials."
        ),
        action_class="write",
        risk_level="medium",
        destructive=False,
        side_effects="delete", idempotency="unsafe_to_retry",
        requires_approval=False,
        approval_reason_template="Device change: confirm asset is correct before commit",
        timeout_seconds=30,
    ),

    # ═══ 4. browser.manage (merged: navigate+extract+screenshot+click) ═══
    "browser.manage": CapabilityManifest(
        tool_id="browser.manage", category="browser", display_name="Browser (unified)",
        description=(
            "Unified Playwright tool. action=navigate, extract, screenshot (reads); "
            "action=click (write)."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ 5. web.manage (merged: search+weather+page.process) ═══
    "web.manage": CapabilityManifest(
        tool_id="web.manage", category="web", display_name="Web (unified)",
        description=(
            "Unified web tool. action=search (web/docs/news), "
            "action=weather (forecast), action=page (summarize/extract/save_artifact)."
        ),
        action_class="network",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=90,
    ),

    # ═══ 6. data.manage (merged: csv+table.extract+table.render+validate) ═══
    "data.manage": CapabilityManifest(
        tool_id="data.manage", category="data", display_name="Data (unified)",
        description=(
            "Unified data tool. action=csv_summarize, table_extract, table_render, validate. "
            "All sub-actions are read-only."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ 7. report.manage (merged: markdown+safe_summary+mermaid+artifact.save) ═══
    "report.manage": CapabilityManifest(
        tool_id="report.manage", category="report", display_name="Report (unified)",
        description=(
            "Unified report tool. action=markdown_render, safe_summary_render, "
            "mermaid_render (reads); action=artifact_save (write)."
        ),
        action_class="write",  # contains artifact.save
        risk_level="low", side_effects="write", writes_artifact=True,
        idempotency="safe_to_retry", timeout_seconds=60,
    ),

    # ═══ 8. config.manage (was config.analysis.run) ═══
    "config.manage": CapabilityManifest(
        tool_id="config.manage", category="config", display_name="Config (unified)",
        description=(
            "Unified config analysis. action=parse, translate, extract_interfaces, "
            "extract_routes, diff, summarize."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),

    # ═══ 9. pcap.manage (was pcap.analysis.run) ═══
    "pcap.manage": CapabilityManifest(
        tool_id="pcap.manage", category="network", display_name="PCAP (unified)",
        description=(
            "Unified PCAP analysis. action=parse, session, filter, align."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=120,
    ),

    # ═══ 10. knowledge.manage (merged: 8 KB tools) ═══
    "knowledge.manage": CapabilityManifest(
        tool_id="knowledge.manage", category="knowledge", display_name="Knowledge (unified)",
        description=(
            "Unified knowledge tool. action=search, read, source_list, "
            "chunk_list, not_found_explain (reads); "
            "action=import, source_manage, source_reindex (writes)."
        ),
        # v3.9.2: visibility treats this as "read" because the canonical
        # knowledge query path is read. Write sub-actions (import/manage/
        # reindex) are gated at execution time, not visibility time.
        action_class="read",
        risk_level="medium", side_effects="write", idempotency="safe_to_retry",
        timeout_seconds=300,
    ),

    # ═══ 11. memory.manage (merged: search+manage+profile) ═══
    "memory.manage": CapabilityManifest(
        tool_id="memory.manage", category="memory", display_name="Memory (unified)",
        description=(
            "Unified memory tool. action=search, profile_get (reads); "
            "action=create, update, confirm, delete, profile_set (writes)."
        ),
        action_class="write",
        risk_level="medium", side_effects="write", idempotency="unknown",
        output_sensitivity="sensitive", timeout_seconds=30,
    ),

    # ═══ 12. skill.manage (merged: list+find+load+inspect) ═══
    "skill.manage": CapabilityManifest(
        tool_id="skill.manage", category="agent", display_name="Skill (unified)",
        description=(
            "Unified skill tool. action=list, find, load, inspect. "
            "All sub-actions are read-only; loading a skill does not "
            "execute the business task."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        allowed_callers=["turn_runner", "rest_api", "job_runner", "graph_runner", "subagent"],
        timeout_seconds=10,
    ),

    # ═══ 13. agent.manage (merged: spawn+team.run+result.get+role.list) ═══
    "agent.manage": CapabilityManifest(
        tool_id="agent.manage", category="agent", display_name="Agent (unified)",
        description=(
            "Unified agent tool. action=role_list, result_get (reads); "
            "action=spawn, team_run (execute, dispatcher enforces approval for team_run)."
        ),
        action_class="execute",
        risk_level="medium",  # base level; team_run escalates via dispatcher
        side_effects="remote_exec", idempotency="unsafe_to_retry",
        requires_approval=False,
        allowed_callers=["turn_runner", "rest_api", "job_runner", "graph_runner"],
        timeout_seconds=300,
    ),

    # ═══ 14. system.manage (merged: 9 system tools) ═══
    "system.manage": CapabilityManifest(
        tool_id="system.manage", category="system", display_name="System (unified)",
        description=(
            "Unified system introspection. action=diagnostics, run_get, "
            "session_get, session_snapshot (reads); "
            "action=review_update, session_checkpoint (writes); "
            "action=session_rewind, session_export (admin/approval)."
        ),
        action_class="admin",
        risk_level="medium",  # contains session.rewind (destructive, approval gated)
        side_effects="write", idempotency="unsafe_to_retry",
        requires_approval=False,  # approval required only for rewind
        approval_reason_template="System: rewinding session discards recent state",
        timeout_seconds=300,
    ),

    # ═══ 15. text.analyze ═══
    "text.analyze": CapabilityManifest(
        tool_id="text.analyze", category="text", display_name="Text Analyze",
        description="Analyze text. action=redact, diff, keywords, classify.",
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=30,
    ),

    # ═══ 16. code.search ═══
    "code.search": CapabilityManifest(
        tool_id="code.search", category="code", display_name="Code Search",
        description="Search codebase using ripgrep (fast) or Python fallback.",
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=60,
    ),

    # ═══ 17. workspace.file ═══
    "workspace.file": CapabilityManifest(
        tool_id="workspace.file", category="workspace", display_name="Workspace File (unified)",
        description=(
            "Unified workspace file tool. action=list, read, read_image (reads); "
            "action=edit, patch, write_artifact (writes)."
        ),
        action_class="write",
        risk_level="medium",
        reads_artifact=True, writes_artifact=True, side_effects="write",
        idempotency="unsafe_to_retry", timeout_seconds=30,
    ),

    # ═══ 18. workspace.artifact ═══
    "workspace.artifact": CapabilityManifest(
        tool_id="workspace.artifact", category="workspace", display_name="Workspace Artifact (unified)",
        description=(
            "Unified workspace artifact tool. action=list, read, diff, export (reads); "
            "action=save, tag, delete (writes, delete requires approval)."
        ),
        action_class="write",
        risk_level="medium",
        reads_artifact=True, writes_artifact=True, side_effects="write",
        idempotency="unsafe_to_retry", timeout_seconds=30,
    ),

    # ═══ 19. workspace.filestore ═══
    "workspace.filestore": CapabilityManifest(
        tool_id="workspace.filestore", category="workspace", display_name="FileStore (unified)",
        description=(
            "Unified FileStore tool. action=references (read cross-refs); "
            "action=import (write into FileStore)."
        ),
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry",
        timeout_seconds=20,
    ),

    # ═══ 20. workspace.metadata.get ═══
    "workspace.metadata.get": CapabilityManifest(
        tool_id="workspace.metadata.get", category="workspace", display_name="Workspace Metadata",
        description="Get workspace metadata and stats.",
        action_class="read",
        risk_level="low", side_effects="none", idempotency="safe_to_retry", timeout_seconds=10,
    ),

    # ═══ 21. workspace.document.pdf.extract_text ═══
    "workspace.document.pdf.extract_text": CapabilityManifest(
        tool_id="workspace.document.pdf.extract_text", category="workspace", display_name="PDF Extract",
        description="Extract text from PDF.",
        action_class="read",
        risk_level="low", reads_artifact=True, side_effects="none",
        idempotency="safe_to_retry", timeout_seconds=60,
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
    if not m:
        return False
    if m.destructive:
        return False
    return m.idempotency == "safe_to_retry"
