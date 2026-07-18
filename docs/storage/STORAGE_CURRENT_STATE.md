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
| Context items | `core/context/context_store.py` through transactional `storage.records` |
| Reference index | `storage/reference_index.py` through `storage.records` |
| Trace records | `observability/store.py` through `storage.records` |
| Approval audit log | `storage/approval_record_store.py` under `workspaces/_runtime/` |
| Token usage | `storage/usage_store.py` |
| Artifact metadata | `storage/artifact_metadata_store.py` |
| Run-artifact links | `storage/run_artifact_store.py` |
| Generic workspace records | `storage/records.py` |
| Workspace discovery | `storage/workspace_store.py` |
| Workspace file path/read-write helpers | `storage/workspace_files.py` |
| Inspection tasks and script overrides | `storage/inspection_store.py` |
| Assurance records | `storage/assurance_store.py` |
| CMDB assets | `storage/cmdb_store.py` |
| Saved remote devices and logs | `storage/remote_store.py` |
| Encrypted credentials | `storage/credential_store.py` |
| PCAP session index | `storage/pcap_store.py` |
| Audit log entries | `storage/audit_store.py` |
| Ecosystem providers | `storage/ecosystem_store.py` |
| Manual review sidecars | `storage/review_store.py` |
| Run record facade | `storage/run_record_store.py` |
| Session checkpoints | `storage/session_checkpoint_store.py` |
| Tool execution history | `storage/tool_history_store.py` |
| Jobs | `jobs/store.py` with per-job and index locks |
| Durable tasks, events, checkpoints | `storage/durable_task_store.py` |
| Delivery records | `storage/delivery_store.py` |
| Trajectories | `storage/trajectory_store.py` |
| Sub-agent runtime | `storage/subagent_store.py` |
| Tool history | `storage/tool_history_store.py` |

## Current Guarantees

- Workspace IDs and every path-bearing run, job, task, checkpoint, and session ID are validated before storage access.
- JSONL read-modify-write operations hold one cross-process, fail-closed transaction lock; lock timeout never falls through into an unlocked write.
- JSONL mutations refuse malformed input instead of silently discarding damaged records.
- Read-only queries do not create missing workspace directories.
- Artifact metadata, run-artifact links, job state/indexes, provider configuration, workspace state, and runtime worker state use atomic writes under file locks.
- CMDB and remote passwords use authenticated AES-GCM ciphertext and an atomically created owner-only workspace key; plaintext passwords are never returned by list APIs.
- Memory write/read is governed by status, scope, TTL, and workspace.
- Tool history, approval audit records, usage records, and runtime events store redacted or structured summaries.
- Provider secrets and local runtime data are ignored by Git.
- Root-level `data/` is not a current storage plane. Durable runtime records live under `workspaces/_runtime/`.
- Backend startup reconciles jobs left in `running` by an interrupted process, and selfcheck reports stale jobs or invalid durable events.

## Cleanup Policy

Safe generated data to remove during maintenance:

- Python caches
- pytest caches
- frontend build output
- generated audit reports
- OS metadata files

Do not delete live workspace data, provider config, or runtime state without an explicit user request.
