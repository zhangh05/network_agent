# File Pipeline

## Principle

**All files flow through ArtifactStore.** No direct file reads, no bypass.

## Pipeline Stages

```
Input → Classification → Policy → Storage → Index → Access
```

### 1. Input

Sources of files:
- **Upload**: user-uploaded files (HTTP multipart)
- **Source path**: files referenced by workspace path
- **Content**: inline content passed as string
- **Agent-generated**: output from agent runs

### 2. Classification

Artifact type detection based on content and context:
- `input_config`: network device configuration input
- `output_config`: translated/deployable configuration
- `report`: generated reports (markdown, html, json, csv)
- `other`: miscellaneous artifacts

### 3. Policy

- **Sensitivity classification**: auto-detected as public / internal / sensitive / secret
- **Secret detection**: scan for keys, passwords, tokens in content
- **Redaction**: strip secrets before storage, before memory, before LLM context

### 4. Storage

```
workspaces/{ws_id}/artifacts/
├── {artifact_id}.json       # metadata
├── {artifact_id}.content    # actual content (if stored)
└── ...
```

Content may be stored on disk or referenced externally depending on size and sensitivity.

### 5. Index

`artifacts.index.json` at workspace root:
```json
{
  "artifacts": {
    "art_<id>": { "type": "...", "scope": "...", "size_bytes": ..., "sha256": "...", "created_at": "..." }
  }
}
```

### 6. Access

All artifact access MUST go through `ArtifactStore` API methods:
- `get_artifact(artifact_id)` — full artifact (subject to sensitivity policy)
- `get_artifact_summary(artifact_id)` — safe summary only
- `list_artifacts(scope)` — list by scope
- `get_artifact_content(artifact_id)` — content (if policy allows)

### Security Layers

| Layer | Guard |
|-------|-------|
| Path validation | `Path.resolve().relative_to()` boundary check |
| Size guard | Pre-read `stat().st_size` + content-length header |
| Redaction | Applied before storage, before memory, before LLM |
| Sensitivity | Blocks content access at API layer for sensitive artifacts |
