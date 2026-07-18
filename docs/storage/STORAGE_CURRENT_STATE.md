# Storage Current State

The current storage model is file-based and workspace-scoped.

All durable user and Agent payloads live in `files/data/`. `files/tmp/` is transient. Business type and ownership come from FileRecord and reference metadata, never from nested payload directories.

## Stores

| Store | Module |
| --- | --- |
| Sessions | `storage/session_store.py` |
| Messages | `storage/message_store.py` |
| Runs | `storage/run_record_store.py` |
| Memory | `storage/memory_governance.py` |
| Artifacts | `artifacts/store.py` |
| Generic workspace records | `storage/records.py` |
| Workspace discovery | `storage/workspace_store.py` |
| Workspace file path/read-write helpers | `storage/workspace_files.py` |
| Inspection tasks and script overrides | `storage/inspection_store.py` |
| PCAP session index | `storage/pcap_store.py` |
| Audit log entries | `storage/audit_store.py` |
| Ecosystem providers | `storage/ecosystem_store.py` |
| Manual review sidecars | `storage/review_store.py` |
| Run record facade | `storage/run_record_store.py` |
| Session checkpoints | `storage/session_checkpoint_store.py` |
| Tool execution history | `storage/tool_history_store.py` |
| Jobs | `jobs/store.py` through `storage/records.py` |
| Durable runtime | `agent/runtime/durable/store.py` through storage path helpers |
| Tool history | `storage/tool_history_store.py` |

## Current Guarantees

- Workspace IDs are validated at API boundaries.
- Memory write/read is governed by status, scope, TTL, and workspace.
- Tool history and runtime events store redacted summaries.
- Provider secrets and local runtime data are ignored by Git.

## Cleanup Policy

Safe generated data to remove during maintenance:

- Python caches
- pytest caches
- frontend build output
- generated audit reports
- OS metadata files

Do not delete live workspace data, provider config, or runtime state without an explicit user request.
