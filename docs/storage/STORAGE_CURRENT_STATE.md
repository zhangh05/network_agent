# Storage Current State

## Overview

The `storage/` package provides a unified file management layer for the workspace.

## Components (v1)

| File | Purpose |
|------|---------|
| `storage/paths.py` | Unified workspace root resolution |
| `storage/schemas.py` | FileRecord and FileReference data models |
| `storage/file_store.py` | File write/read/index operations |
| `storage/reference_index.py` | Cross-reference index (file ↔ entity) |
| `storage/policy.py` | Size limits, kind classification, retention |
| `storage/gc.py` | Dry-run garbage collection |

## FileRecord Fields (v1)

- `file_id` — unique ID (`file_<uuid16>`)
- `workspace_id` — workspace scope
- `logical_type` — user_upload, artifact_output, pcap_result, report, etc.
- `file_kind` — text, binary, pcap, json, markdown, etc.
- `path` — workspace-relative path
- `original_name`, `mime_type`, `binary`, `size_bytes`, `sha256`
- `created_at`, `created_by`, `session_id`, `run_id`, `source`
- `sensitivity`, `lifecycle`, `retention_policy`, `metadata`

## Integration Status

| Module | Status |
|--------|--------|
| `workspace/manager.py` | ✅ Calls `ensure_workspace_storage_dirs` |
| `artifacts/store.py` | ✅ Uses `write_agent_output`, sets `file_id` |
| `artifacts/schemas.py` | ✅ Added `file_id` field to `ArtifactRecord` |
| `config_analysis/service.py` | ✅ Supports `file_id` parameter |
| `workspace/message_store.py` | ⏳ Planned |
| `agent/modules/pcap/service.py` | ⏳ Planned |
| `agent/modules/knowledge/ingestion.py` | ⏳ Planned |
| `backend/api/artifact_routes.py` | ⏳ Planned |

## Directory Structure

```
workspaces/<ws>/
  files/
    user_upload/original/     # uploaded originals (preserved)
    user_upload/staged/       # pre-processing staging
    agent_output/config/      # translated/analyzed configs
    agent_output/pcap/        # PCAP analysis results
    agent_output/report/      # generated reports
    agent_output/export/      # general exports
    agent_output/message/     # large message content
    knowledge/source/         # knowledge import originals
    knowledge/normalized/     # normalized markdown
    tmp/                      # atomic write staging
    upload/                   # [legacy compat]
    agent/                    # [legacy compat]
  index/
    files.jsonl               # file record index
    references.jsonl          # cross-reference index
  inbox/
  context/
  sessions/
  runs/
  sys/
```

## Pending Work

- Message store: route large content through artifact/file store
- PCAP service: file_id input, result artifacts
- Knowledge ingestion: file_id import, normalized file records
- Artifact upload route: preserve originals via FileStore
- Legacy path migration (files/upload → files/user_upload)
- Full GC implementation
