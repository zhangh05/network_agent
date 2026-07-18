# Storage Boundaries

## Local Data Roots

| Path | Purpose | Git |
| --- | --- | --- |
| `workspaces/<workspace_id>/` | User workspace files and app data | ignored |
| `workspaces/_runtime/` | Durable task/runtime state | ignored |
| `data/` | Local JSON/JSONL runtime stores | ignored unless explicitly tracked |
| `logs/` | Local logs | ignored |
| `config/providers/` | Provider config and secrets | ignored |
| `artifacts/` | Source code for artifact store, not artifact payload data | tracked |

## Boundary Rules

- Workspace data is scoped by validated `workspace_id`.
- Store functions should not invent a workspace for caller mistakes.
- Deletion must be scoped and explicit.
- Redacted summaries may be returned in list APIs; raw secret-bearing payloads must not.
- Business modules call storage repositories or record helpers for workspace
  persistence. They must not assemble `workspace_root()/module/*.json(l)` paths
  or perform ad hoc JSON/JSONL file writes.

## Runtime State

Durable runtime state lives under workspace runtime storage and is addressed by task/session/workspace IDs. Task checkpoints are implementation state, not user documents.

## Managed Files

- `files/data/` is the only durable payload directory. Uploads, artifacts, reports, packet captures, translated configurations, and normalized knowledge documents are distinguished by `FileRecord.logical_type`, not by directory names.
- `files/tmp/` is the only transient payload directory. Temporary parser and executor inputs must be purged after use.
- Business stores hold `file_id` references and must not copy payloads into module-owned directories.
- Frontend file views are projections of backend APIs and FileRecords; they never enumerate workspace directories.

## Knowledge Library

- `context/items.jsonl` is the metadata and chunk index SSOT. A knowledge source uses a stable `ksrc_<id>` identifier.
- Upload payloads are temporary parser inputs and are purged after normalization.
- Every indexed source has exactly one persistent Markdown document at `files/data/<source_id>.md`.
- The source record's `normalized_file_id` points to that Markdown file. Code must not infer source identity from filenames, titles, vendors, or protocol keywords.
- Rename changes source and chunk metadata; it does not rewrite document content. Disable controls retrieval visibility. Delete removes the normalized document and its source/chunk projections.
- The frontend manages knowledge only through `/api/knowledge/*`; it does not enumerate or mutate workspace files directly.
