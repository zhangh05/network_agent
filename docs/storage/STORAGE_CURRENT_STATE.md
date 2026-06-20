# Storage Final State

## Overview

The `storage/` package provides the unified file management layer. All legacy compatibility code has been removed.

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
| `storage/legacy_migration.py` | ✅ Legacy data migration tool |

## FileStore Components

| File | Purpose |
|------|---------|
| `storage/paths.py` | Unified workspace root resolution |
| `storage/schemas.py` | FileRecord and FileReference data models |
| `storage/file_store.py` | Managed file write/read/index/delete |
| `storage/reference_index.py` | Cross-reference index |
| `storage/policy.py` | Size limits, kind classification |
| `storage/gc.py` | Dry-run garbage collection |
| `storage/legacy_migration.py` | Historical data migration |

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

## Removed Legacy Paths

- `files/upload` — removed from new workspace init and runtime
- `files/agent` — removed from new workspace init and runtime
- `tracking_only` / `legacy_artifact_store` — removed from runtime
- PCAP sidecar read/write — removed from runtime
- Artifact legacy path fallback — removed from read operations

## Migration Tool

For historical workspaces with legacy data:

```bash
python scripts/storage_legacy_migrate.py --all --dry-run
python scripts/storage_legacy_migrate.py --all --apply
python scripts/storage_legacy_migrate.py --workspace default --dry-run
python scripts/storage_legacy_migrate.py --workspace default --apply
```

## Pending Work

- Physical GC / hard delete policy
- Optional historical data archive/export
