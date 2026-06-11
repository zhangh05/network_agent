# Security

## Tool Safety

- `ToolRouter` only accepts model-visible tool names.
- Disabled, forbidden, and non-LLM-callable tools are not exposed to the model.
- `command.approved_exec` and `powershell.approved_script` are registered but disabled.
- High-risk tool execution requires approval state matching tool and workspace.
- Tool history and approvals are persisted in `data/tool_history.json` and `data/tool_approvals.json`.

## Forbidden Runtime Claims

The system must not claim or expose:

- real device execution
- direct production config push
- SSH/Telnet/SNMP/nmap/ping sweep device operations
- unrestricted file read/write
- arbitrary shell execution
- deployable network configuration without human review

## Knowledge Ingestion Boundaries

`knowledge.import_file` is constrained to workspace upload/inbox paths and rejects traversal, symlink escape, missing files, oversized files, and DOCX archive bombs.

## Artifacts

Artifacts can be sensitive. UI and API code should preserve sensitivity metadata and avoid promoting translated configs as directly deployable.
