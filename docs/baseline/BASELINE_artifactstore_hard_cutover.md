# BASELINE: ArtifactStore Hard Cutover

## Status

ArtifactStore is moving from legacy per-artifact meta files to indexed metadata under `index/artifacts.jsonl`.

## Scope

- Artifact content is written through `storage.file_store.write_agent_output`.
- Artifact metadata is written to `index/artifacts.jsonl`.
- Artifact reads require `file_id` and use FileStore.
- Artifact tag/delete/promote update the indexed metadata record.
- Workspace artifact file tool writes through FileStore instead of legacy agent directories.
- Legacy migration links migrated artifact metadata to migrated FileStore records when possible.

## Removed Runtime Patterns

- New artifact metadata writes to legacy agent meta files.
- New artifact content fallback writes to legacy agent directories.
- Artifact lookup through legacy upload/agent meta paths.
- Tool-level artifact tag updates through legacy meta files.
- Workspace write_artifact direct writes to legacy agent directories.

## Validation

- `harness/test_artifactstore_hard_cutover.py`
- Existing artifact baseline tests
- Existing storage migration tests
- Full pytest before merge
