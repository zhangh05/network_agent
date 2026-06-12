# Security

## Tool Safety

- `ToolRouter` only accepts model-visible tool names.
- Disabled, forbidden, and non-LLM-callable tools are not exposed to the model.
- `command.approved_exec` and `powershell.approved_script` are registered but disabled.
- `weather.current`, `weather.forecast`, and `news.search` are registered but disabled.
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

`config push` is explicitly outside the current model-visible runtime boundary.

## Knowledge And Memory Boundaries

- Uploaded knowledge files are imported from workspace-controlled temporary paths.
- Search and chunk APIs return safe excerpts, not full raw sensitive files.
- Memory writes are redacted and policy checked before persistence.
- Memory records are projected into RAG best-effort only after passing write policy.
- Memory conflict metadata is advisory and should be shown to users rather than silently ignored.

## Artifacts

Artifacts can be sensitive. UI and API code should preserve sensitivity metadata and avoid promoting translated configs as directly deployable.

## LLM Configuration

Provider keys are local configuration. Do not commit real keys, local provider config, or runtime diagnostic files that include local status.
