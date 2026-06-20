# Backend API Contract

## Response Envelope

All backend APIs return a consistent envelope:

**Success:**
```json
{
  "ok": true,
  "status": "ok",
  "summary": "",
  "data": {},
  "errors": []
}
```

**Failure:**
```json
{
  "ok": false,
  "status": "failed",
  "summary": "",
  "error_code": "",
  "errors": []
}
```

## Stable APIs

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/tools/catalog` | Tool catalog |
| GET | `/api/workspaces/<ws>/status` | Workspace stats + health |
| GET | `/api/workspaces/<ws>/storage/health` | Storage doctor result |
| GET | `/api/workspaces/<ws>/files/<file_id>/references` | File reference index |
| GET | `/api/workspaces/<ws>/artifacts/<artifact_id>/references` | Artifact reference index |
| GET | `/api/workspaces/<ws>/reference-graph` | Reference graph |

## Error Codes

| Code | Meaning |
|------|---------|
| `WORKSPACE_NOT_FOUND` | Workspace does not exist |
| `INVALID_WORKSPACE_ID` | Workspace ID is invalid |
| `FILE_NOT_FOUND` | FileRecord not found |
| `FILE_NOT_ACCESSIBLE` | File exists in index but not on disk |
| `ARTIFACT_NOT_FOUND` | ArtifactRecord not found |
| `PCAP_SESSION_NOT_FOUND` | PCAP session not in memory or index |
| `REFERENCE_NOT_FOUND` | ReferenceIndex entry not found |
| `TOOL_NOT_ALLOWED` | Tool is forbidden or not permitted |
| `RISK_APPROVAL_REQUIRED` | High-risk action needs approval |
| `INTERNAL_ERROR` | Unexpected backend error |

## Stability Rule

Frontend refactor may depend on this contract after PR #20 is merged.
New APIs in this PR use the envelope; legacy APIs adopt it progressively.
