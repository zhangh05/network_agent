# Backend API Contract

Current backend contract (v3.8). This page is the backend-facing companion to
`docs/API.md`; keep endpoint names and response shapes aligned with
`backend/main.py` and `backend/api/*_routes.py`.

## Response Envelope

Successful list endpoints return an explicit collection and count when
available:

```json
{"ok": true, "items": [], "count": 0, "workspace_id": "default"}
```

Successful item endpoints return the item under a named key:

```json
{"ok": true, "item": {}, "workspace_id": "default"}
```

Errors use the shared error shape:

```json
{"ok": false, "error": "CODE", "message": "detail", "details": {}}
```

## Required Runtime Surfaces

| Method | Path | Contract |
|--------|------|----------|
| `POST` | `/api/agent/message` | Main agent entry. Returns `final_response`, `events`, `run_id`, `trace_id`, `session_id`, `metadata`, and tool-call summaries. |
| `WS` | `/ws/agent` | Live agent stream. Emits token/event messages and a final payload compatible with `AgentResult`. |
| `GET` | `/api/runs/recent?workspace_id=<ws>&session_id=<sid>` | Recent runs scoped to workspace and optionally session. |
| `GET` | `/api/workspaces/<ws>/runs/<run_id>/trace` | Persisted trace with real/synthetic event counters. |
| `GET` | `/api/workspaces/<ws>/runs/<run_id>/decision` | Decision report for routing, retrieval, tool planning, and trace truth. |
| `GET` | `/api/runtime/summary` | Runtime truth source for capability and tool counts. |
| `GET` | `/api/runtime/selfcheck` | Runtime consistency issues. |
| `GET` | `/api/workspaces/<ws>/selfcheck` | Workspace storage and trace consistency issues. |

## Capability And Tool Surfaces

| Method | Path | Contract |
|--------|------|----------|
| `GET` | `/api/capabilities` | Public capability projection from manifests. |
| `GET` | `/api/tools/catalog` | Canonical tool catalog visible to the UI. |
| `POST` | `/api/tools/invoke` | Execute one canonical tool invocation after policy and approval checks. |
| `POST` | `/api/tools/dry-run` | Return approval/policy decision without executing the tool. |

The canonical registry lives in `tool_runtime/canonical_registry.py`; docs and
runtime checks should agree with that source.

Tool invocation requests use `arguments` for handler inputs and pass
`workspace_id` as the query parameter consumed by the backend route.

## Knowledge And PCAP Surfaces

| Method | Path | Contract |
|--------|------|----------|
| `GET` | `/api/knowledge/sources` | List knowledge sources backed by `agent/modules/knowledge/`. |
| `GET` | `/api/knowledge/search?q=<query>` | Search indexed knowledge chunks. |
| `POST` | `/api/pcap/parse` | Parse uploaded PCAP data into a persisted session. |
| `GET` | `/api/pcap/session/<sid>` | Load a persisted PCAP session. |
| `POST` | `/api/pcap/filter` | Filter packet session data by 5-tuple and summary parameters. |

Canonical session lookup: `GET /api/pcap/session/<sid>`.

## Frontend Compatibility Rules

- Frontend API calls are rooted at `/api` through `frontend/src/api/client.ts`.
- SSE helpers must use the same API base as HTTP helpers.
- `final_response` is a string; consumers must not expect
  `final_response.content`.
- Tool and capability counts come from backend truth endpoints, not hard-coded
  frontend constants.
- Trace consumers must distinguish real events from synthetic fallback events.

## Security Rules

- Unsafe API writes reject cross-origin browser requests even when token auth is
  disabled for local desktop use.
- Workspace deletion requires explicit confirmation and cannot delete
  `default`.
- CMDB and Remote saved-device records must not persist device passwords.
