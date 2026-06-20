# BASELINE: Storage Legacy Compatibility Removed

## Status

Storage refactor and legacy cleanup completed.

## Included

- FileStore foundation merged
- Artifact upload migrated to FileStore
- ArtifactStore writes through FileStore.write_agent_output
- SessionMessage large content uses managed artifacts
- Knowledge import supports file_id
- Knowledge normalized content stored as FileRecord
- PCAP parse supports file_id
- PCAP result artifacts generated
- Runtime legacy storage compatibility removed
- Legacy migration CLI added
- New workspaces no longer initialize files/upload or files/agent
- Runtime PCAP sidecar fallback removed
- Artifact legacy path fallback removed

## Migration Tool

Use:

```bash
python scripts/storage_legacy_migrate.py --all --dry-run
python scripts/storage_legacy_migrate.py --all --apply
```

## Data Safety

No historical workspace data is deleted by cleanup code.

Legacy data must be migrated through:

```bash
scripts/storage_legacy_migrate.py
```

## Validation

- storage legacy migration tests passed
- storage legacy removal contract tests passed
- storage foundation tests passed
- upload migration tests passed
- core migration tests passed
- knowledge file_id tests passed
- full pytest passed

## Merge Points

- PR #16: FileStore foundation and core migration
- PR #17: final cleanup contract
- PR #18: legacy compatibility removal
