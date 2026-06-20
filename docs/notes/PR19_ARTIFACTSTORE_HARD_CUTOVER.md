# PR19 ArtifactStore Hard Cutover

## Summary

This branch hardens ArtifactStore runtime storage after the legacy compatibility cleanup.

## Changes

- Artifact metadata is written to `index/artifacts.jsonl`.
- Artifact content remains FileStore-only through `write_agent_output`.
- Artifact creation fails if FileStore write fails; it does not fall back to a legacy path.
- Artifact tag/delete/promote updates go through indexed artifact records.
- Workspace write_artifact tool writes through FileStore and returns file_id.
- Legacy migration links migrated artifact metadata to migrated FileStore file_id when possible.

## Tests

- `harness/test_artifactstore_hard_cutover.py`
- `harness/test_artifactstore_hard_cutover_contract.py`
