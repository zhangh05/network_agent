# Artifact Design

## Current Closure State

Baseline entering completion: `ac6cadd`.

Artifacts are real backend records, not UI-fabricated data. Run history, memory, jobs, reports, and traces may reference artifacts by safe refs only. Browser localStorage is not an artifact, job, report, or run-history store.

Tool Runtime trace metadata may include `artifact_ids`, never artifact content.

## ArtifactRecord

All artifacts are tracked as `ArtifactRecord` instances:

| Field | Type | Description |
|-------|------|-------------|
| `artifact_id` | str | Format `art_<uuid16>` (16-char hex) |
| `artifact_type` | str | input_config, output_config, report, etc. |
| `scope` | enum | run / workspace / shared / global / temp |
| `sensitivity` | enum | public / internal / sensitive / secret |
| `lifecycle` | str | Lifecycle state tag |
| `sha256` | str | Content fingerprint only — NOT the ID |
| `size_bytes` | int | Content size in bytes |
| `title` | str | Human-readable title |
| `summary` | str | Safe summary (no secrets) |
| `metadata` | dict | Arbitrary key-value metadata |
| `created_at` | datetime | Creation timestamp |

## Source Path Security

`source_path` is resolved with `Path.resolve().relative_to()` enforcing strict directory boundary. The resolved path MUST be within the workspace artifacts directory; any escape attempt is rejected.

## Upload Guards

1. **Content-Length pre-check**: reject before reading if exceeds limit
2. **stat().st_size before read_text**: filesystem-level size guard
3. **source_path size guard**: same as file size guard
4. **Content size guard**: measured in UTF-8 bytes after read

## Size Limits

- Default: **10 MB** per artifact
- Override: `NETWORK_AGENT_MAX_UPLOAD_MB` environment variable
- Oversized content: no artifact index entry, no partial metadata — clean rejection

## Auto-Saved Artifacts

| Trigger | Artifact Type | Scope |
|---------|---------------|-------|
| Run input from `source_config` | `input_config` | run |
| Deployable config output | `output_config` | run |
| Report generation | `report` | workspace |
| Export operation | `report` | workspace |

## Job Artifact Aggregation

Job aggregates its child artifacts:
- `input_artifacts`: collected from run input_config artifacts
- `output_artifacts`: collected from run output_config artifacts
- `report_artifacts`: collected from run report artifacts

## Storage Constraints

| Layer | Stores |
|-------|--------|
| Memory | Only `artifact_refs` (IDs + summary), NO full content |
| LLM safe context | Artifact summary only, max 10 refs |
| Trace | Artifact metadata only (id, type, size, sha256), NO content |
