# Storage Final State

## Overview

The `storage/` package is the only supported file management layer.

## Completed Migration

| Module | Status |
|--------|--------|
| `workspace/manager.py` | ✅ Calls `ensure_workspace_storage_dirs` |
| `artifacts/store.py` | ✅ Writes through `FileStore.write_agent_output`; requires `file_id` for reads |
| `artifacts/schemas.py` | ✅ `ArtifactRecord.file_id` |
| `backend/api/artifact_routes.py` | ✅ Upload preserves originals via `import_user_upload` |
| `workspace/message_store.py` | ✅ Large content via managed artifacts |
| `agent/modules/pcap/service.py` | ✅ `file_id` parse; result artifacts; no sidecar |
| `agent/modules/knowledge/ingestion.py` | ✅ `file_id` import; normalized FileRecord |
| `config_analysis/service.py` | ✅ `file_id` parameter |
| `storage/reference_index.py` | ✅ Cross-reference index |

## FileStore Components

| File | Purpose |
|------|---------|
| `storage/paths.py` | Unified workspace root resolution |
| `storage/schemas.py` | FileRecord and FileReference data models |
| `storage/file_store.py` | Managed file write/read/index/delete |
| `storage/reference_index.py` | Cross-reference index |
| `storage/policy.py` | Size limits, kind classification |
| `storage/gc.py` | Dry-run garbage collection |

## Directory Structure

```
workspaces/<ws>/
  files/
    user_upload/original/     # uploaded originals
    agent_output/config/      # config analysis
    agent_output/pcap/        # PCAP results
    agent_output/report/      # reports
    agent_output/export/      # exports
    agent_output/message/     # large messages
    knowledge/source/         # knowledge imports
    knowledge/normalized/     # normalized markdown
    tmp/                      # atomic writes
  index/
    files.jsonl               # file records
    references.jsonl          # cross-references
    artifacts.jsonl           # artifact records
  inbox/
  context/
  sessions/
  runs/
  sys/
```

## Removed Paths

- Removed artifact-store markers are not accepted by runtime
- PCAP sidecar read/write — removed from runtime
- Artifact path fallback — removed from read operations

There is no migration entrypoint in the runtime tree. Current workspaces use
the FileStore/ArtifactStore indexes as the source of truth.

## Pending Work

- Physical GC / hard delete policy
- Optional historical data archive/export
