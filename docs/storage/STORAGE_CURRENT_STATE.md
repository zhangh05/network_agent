# Storage Current State (Final)

## Overview

The `storage/` package provides a unified file management layer for the workspace.

## Completed Migration

| Module | Status |
|--------|--------|
| `workspace/manager.py` | ✅ Calls `ensure_workspace_storage_dirs` |
| `artifacts/store.py` | ✅ Writes through `FileStore.write_agent_output` with `file_id` |
| `artifacts/schemas.py` | ✅ Added `file_id` field to `ArtifactRecord` |
| `backend/api/artifact_routes.py` | ✅ Upload preserves originals via `import_user_upload` |
| `workspace/message_store.py` | ✅ Large content routes through `save_artifact` + FileStore |
| `agent/modules/pcap/service.py` | ✅ Supports `file_id`; result artifacts; no new sidecar writes |
| `agent/modules/knowledge/ingestion.py` | ✅ import supports `file_id`; normalized FileRecord |
| `config_analysis/service.py` | ✅ Supports `file_id` parameter |
| `storage/reference_index.py` | ✅ Links files to artifacts/messages/knowledge/pcap |

## FileStore Components

| File | Purpose |
|------|---------|
| `storage/paths.py` | Unified workspace root resolution |
| `storage/schemas.py` | FileRecord and FileReference data models |
| `storage/file_store.py` | Managed file write/read/index/delete |
| `storage/reference_index.py` | Cross-reference index (file ↔ entity) |
| `storage/policy.py` | Size limits, kind classification, retention |
| `storage/gc.py` | Dry-run garbage collection |

## FileRecord Fields

- `file_id` — unique ID (`file_<uuid16>`)
- `workspace_id` — workspace scope
- `logical_type` — user_upload, artifact_output, pcap_result, report, etc.
- `file_kind` — text, binary, pcap, json, markdown, etc.
- `path` — workspace-relative path
- `original_name`, `mime_type`, `binary`, `size_bytes`, `sha256`
- `created_at`, `created_by`, `session_id`, `run_id`, `source`
- `sensitivity`, `lifecycle`, `retention_policy`, `metadata`

## Directory Structure (Current)

```
workspaces/<ws>/
  files/
    user_upload/original/     # uploaded originals (current)
    agent_output/config/      # translated/analyzed configs
    agent_output/pcap/        # PCAP analysis results
    agent_output/report/      # generated reports
    agent_output/export/      # general exports
    agent_output/message/     # large message content
    knowledge/source/         # knowledge import originals
    knowledge/normalized/     # normalized markdown
    tmp/                      # atomic write staging
    upload/                   # [legacy compat, read-only]
    agent/                    # [legacy compat, metadata only]
  index/
    files.jsonl               # file record index
    references.jsonl          # cross-reference index
  inbox/
  context/
  sessions/
  runs/
  sys/
```

## Compatibility

Legacy directories retained for read compatibility only:

- `files/upload` — historical read compatibility; no new writes
- `files/agent` — legacy artifact metadata and read fallback; no new content writes

## Pending Work

- UI/module consumers fully switching to `file_id`
- Historical workspace data migration
- Legacy path migration (optional)
- Physical GC / hard delete
