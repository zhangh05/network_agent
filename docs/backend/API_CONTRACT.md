# API Contract — canonical response shapes and error conventions

## Canonical response envelope

### Success (single object)
```json
{
  "ok": true,
  "item": { ... },
  "workspace_id": "default"
}
```

### Success (list)
```json
{
  "ok": true,
  "items": [ ... ],
  "count": 42,
  "workspace_id": "default"
}
```

### Error
```json
{
  "ok": false,
  "error": "MACHINE_READABLE_CODE",
  "message": "Human-readable description",
  "details": { ... }
}
```

### HTTP status codes
| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid input, missing field, invalid workspace_id) |
| 404 | Resource not found |
| 413 | Payload too large |
| 500 | Internal server error |

### Removed shapes (do NOT use)
```
{"ok": false, "detail": "..."}     → use "message"
{"status": "failed", ...}          → use "ok": false
{"summary": "...", "error_code": "..."} → use "error"/"message"
```

---

## Core API reference

### POST /api/agent/message
```
Request:  { "workspace_id": "...", "message": "...", "session_id": "..." }
Response: { "ok": true, "reply": "...", "session_id": "..." }
Error:    { "ok": false, "error": "LLM_UNAVAILABLE", "message": "..." }
```

### GET /api/sessions/<sid>/messages
```
Response: { "ok": true, "messages": [...], "count": N, "session_id": "sid" }
Error:    { "ok": false, "error": "SESSION_NOT_FOUND", "message": "...", 404 }
```

### GET /api/runs/recent
```
Response: { "ok": true, "runs": [...], "count": N }
Error:    { "ok": false, "error": "INTERNAL_ERROR", "message": "...", 500 }
```
Sensitive fields NEVER returned: source_config, raw_config, api_key, password, token, secret.

### GET /api/workspaces/<ws>/runs/<run_id>/decision
```
Response: { "ok": true, "item": { "schema_version": "decision_report.v2", ... }, "workspace_id": "ws" }
Error:    { "ok": false, "error": "DECISION_REPORT_NOT_FOUND", "message": "...", 404 }
```

### GET /api/workspaces/<ws>/artifacts
```
Response: { "ok": true, "artifacts": [...], "workspace_id": "ws" }
Error:    { "ok": false, "error": "INVALID_WORKSPACE_ID", "message": "...", 400 }
```

### POST /api/workspaces/<ws>/artifacts
```
Request:  { "content": "...", "artifact_type": "...", "title": "..." }
Response: { "ok": true, "artifact": { "artifact_id": "...", "file_id": "...", ... } }
Error:    { "ok": false, "error": "...", "message": "...", 400 }
```

### POST /api/workspaces/<ws>/artifacts/upload
```
Request:  multipart/form-data with 'file' field
Response: { "ok": true, "file": { "file_id": "...", ... }, "artifact": {...} or null }
Error:    { "ok": false, "error": "no file provided", "message": "...", 400 }
```

### GET /api/workspaces/<ws>/artifacts/<aid>/content
```
Response: { "ok": true, "content": "...", "metadata": {...} }
Error:    { "ok": false, "error": "ARTIFACT_NOT_FOUND", "message": "...", 404 }
```

### POST /api/pcap/parse
```
Request:  multipart/form-data with 'file' field
Response: { "ok": true, "session_id": "...", "file_id": "...", "total_packets": N, "connections": [...] }
Error:    { "ok": false, "error": "no file provided", "message": "...", 400 }
```

### POST /api/pcap/parse-file
```
Request:  { "workspace_id": "default", "file_id": "file_..." }
Response: { "ok": true, "session_id": "...", "file_id": "...", "total_packets": N, "connections": [...] }
Error:    { "ok": false, "error": "missing_file_id|pcap_parse_failed", "message": "...", 400 }
```

### GET /api/pcap/session/<sid>
```
Response: { "ok": true, "session_id": "...", "filename": "...", "total_packets": N, "connections": [...] }
Error:    { "ok": false, "error": "PCAP_SESSION_NOT_FOUND", "message": "...", 404 }
```

### POST /api/pcap/filter
```
Request:  { "session_id": "...", "filter": "tcp.port == 80" }
Response: { "ok": true, "packets": [...] }
Error:    { "ok": false, "error": "PCAP_SESSION_NOT_FOUND", "message": "...", 404 }
```

### GET /api/runtime/health
```
Response: { "ok": true, "status": "healthy", "components": {...} }
```

### GET /api/runtime/selfcheck
```
Response: { "ok": true, "status": "ok", "checks": [...] }
```

---

## Sensitive fields — never returned by any API

| Field | Reason |
|-------|--------|
| `api_key` | Credential |
| `password` | Credential |
| `token` | Credential |
| `secret` | Credential |
| `authorization` | Credential |
| `source_config` | Raw user config |
| `raw_config` | Raw user config |
| `private_key` | Credential |
| `community` | SNMP credential |
| `pre-shared-key` | VPN credential |

---

## Response helper modules

- `backend/core/responses.py` — canonical envelope helpers (P2-C)

All backend code should use `backend.core.responses` for response envelopes.

---

## Version

- Document version: v1.0
- Schema version: api_contract.v1
- Last updated: 2026-06-21
