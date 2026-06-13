# Security

## Tool Safety

- `ToolRouter` only accepts model-visible tool names.
- Disabled, forbidden, and non-LLM-callable tools are not exposed to the model.
- `weather.current` and `weather.forecast` are enabled medium-risk structured public weather tools with Web fallback; `news.search` is public Web-backed. Answers must cite sources and account for freshness.
- `shell.exec`, `powershell.exec`, and `python.exec` are enabled and model-visible, but execution requires approval state matching tool and workspace.
- Approved execution tools accept shell, PowerShell, or Python commands but require user approval via the frontend approval dialog. All three are risk=high and requires_approval=True.
- `approval_id` is trusted only when supplied by `/api/tools/invoke` after approval validation or by a trusted `ToolRuntimeContext`; an LLM-supplied `approval_id` inside tool arguments does not bypass approval.
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
