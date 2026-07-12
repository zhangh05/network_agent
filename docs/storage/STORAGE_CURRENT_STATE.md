# Storage Current State

The current storage model is file-based and workspace-scoped.

All durable user and Agent payloads live in `files/data/`. `files/tmp/` is transient. Business type and ownership come from FileRecord and reference metadata, never from nested payload directories.

## Stores

| Store | Module |
| --- | --- |
| Sessions | `workspace/session_store.py` |
| Messages | `workspace/message_store.py` |
| Runs | `workspace/run_store.py` |
| Memory | `workspace/memory_governance.py` |
| Artifacts | `artifacts/store.py` |
| Jobs | `jobs/store.py` |
| Durable runtime | `agent/runtime/durable/store.py` |
| Tool history | `backend/api/runtime_routes.py` |

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
