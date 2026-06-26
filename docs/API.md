# API Reference

Current API endpoints (v3.8).

## Canonical Response Envelope

Success:
```json
{"ok": true, "item": {}, "workspace_id": "default"}
{"ok": true, "items": [], "count": 0, "workspace_id": "default"}
```

Error:
```json
{"ok": false, "error": "CODE", "message": "detail", "details": {}}
```

## Core Agent

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/agent/message` | Main agent entry. Body: `{message, workspace_id, session_id?, stream_mode?}`. Response: `{ok, final_response, events[], run_id, session_id, ...}` |
| `GET` | `/api/agent/status` | Agent runtime status |
| `GET` | `/api/agent/usage` | Token/cost usage: `{call_count, total_tokens, input_tokens, output_tokens, estimated_cost}` |

## WebSocket

| Path | Purpose |
|------|---------|
| `WS /ws/agent` | Real-time agent streaming. Sends `{type: "token", content: "..."}` for live tokens. |

## Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/sessions?workspace_id=<ws>&status=active` | List sessions |
| `POST` | `/api/sessions` | Create session: `{workspace_id, title?}` |
| `GET` | `/api/sessions/<id>` | Get session detail |
| `PUT` | `/api/sessions/<id>` | Update session |
| `DELETE` | `/api/sessions/<id>?workspace_id=<ws>&confirm=true` | Permanent delete (requires confirm) |
| `POST` | `/api/sessions/<id>/archive` | Archive session. Also marks linked job as succeeded. |
| `POST` | `/api/sessions/<id>/restore` | Restore archived session. Re-activates linked job. |
| `POST` | `/api/sessions/<id>/soft-delete` | Soft delete. Marks linked job as cancelled. |
| `GET` | `/api/sessions/<id>/messages` | Get session messages |

## Runs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/runs/recent?workspace_id=<ws>&session_id=<sid>` | Recent runs (filters by session_id) |
| `GET` | `/api/workspaces/<ws>/runs/<run_id>/trace` | Run trace events |
| `GET` | `/api/workspaces/<ws>/runs/<run_id>/decision` | Per-run decision report |

## Jobs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/jobs?workspace_id=<ws>` | List jobs (filters out sessions that no longer exist) |
| `POST` | `/api/jobs` | Create job |
| `GET` | `/api/jobs/<id>` | Get job detail |
| `GET` | `/api/jobs/<id>/events` | Job events timeline |
| `GET` | `/api/jobs/<id>/logs` | Job logs |
| `GET` | `/api/jobs/<id>/artifacts` | Job artifacts (aggregated from run indexes) |
| `POST` | `/api/jobs/<id>/cancel` | Cancel job |
| `POST` | `/api/jobs/<id>/retry` | Retry job |

## Artifacts

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workspaces/<ws>/artifacts` | List artifacts |
| `POST` | `/api/workspaces/<ws>/artifacts` | Create artifact |
| `POST` | `/api/workspaces/<ws>/artifacts/upload` | Upload artifact |
| `GET` | `/api/workspaces/<ws>/artifacts/<id>/content` | Get artifact content |

## Memory

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/memory/status` | Memory system status |
| `POST` | `/api/memory/write` | Write memory record |
| `POST` | `/api/memory/search` | Search memory |
| `GET` | `/api/memory/list` | List memory records |
| `POST` | `/api/memory/confirm` | Confirm memory |
| `DELETE` | `/api/memory/<id>` | Soft-delete memory |

## Knowledge

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/knowledge/sources` | List knowledge sources |
| `GET` | `/api/knowledge/sources/<id>` | Get source |
| `GET` | `/api/knowledge/chunks/<id>` | Get chunk |
| `GET` | `/api/knowledge/search?q=<query>` | Search knowledge |
| `POST` | `/api/knowledge/upload` | Upload and index a knowledge document |
| `POST` | `/api/knowledge/sources/from-artifact` | Create a knowledge source from an artifact |

## PCAP

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/pcap/parse` | Parse PCAP file (multipart upload) |
| `GET` | `/api/pcap/session/<id>` | Get PCAP session |
| `POST` | `/api/pcap/filter` | Filter PCAP by 5-tuple |

## Runtime / Diagnostics

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/runtime/health` | Component health: `{components[], summary{ok,warning,error}}` |
| `GET` | `/api/runtime/selfcheck` | System self-check: `{status, issues[]}` |
| `GET` | `/api/workspaces/<ws>/retention/preview` | Retention policy preview |
| `POST` | `/api/workspaces/<ws>/retention/apply` | Apply retention policy |
| `GET` | `/api/workspaces/<ws>/archive/preview` | Archive policy preview |
| `POST` | `/api/workspaces/<ws>/archive/apply` | Apply archive policy |

## LLM Configuration

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/agent/llm/config` | Get LLM config |
| `POST` | `/api/agent/llm/config` | Set LLM config |
| `DELETE` | `/api/agent/llm/config` | Reset LLM config |
| `GET` | `/api/agent/llm/providers` | List providers |
| `GET` | `/api/agent/llm/providers/<id>` | Get provider |
| `POST` | `/api/agent/llm/providers/<id>` | Update provider |
| `DELETE` | `/api/agent/llm/providers/<id>` | Delete provider |
| `POST` | `/api/agent/llm/activate` | Activate provider |

## Capabilities & Modules

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/capabilities` | Capability manifest (YAML projection) |
| `GET` | `/api/modules` | List modules |
| `GET` | `/api/modules/<name>/status` | Module status |
| `GET` | `/api/registry/status` | Registry status |
| `POST` | `/api/registry/reload` | Reload registry |

## Context & Prompts

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/context/status` | Context runtime status |
| `POST` | `/api/context/build` | Build context: `{workspace_id, session_id}` |
| `GET` | `/api/prompts` | List prompt templates |
| `GET` | `/api/prompts/<id>` | Get prompt |
| `POST` | `/api/prompts/render` | Render prompt: `{prompt_id, variables}` |

## Reviews

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workspaces/<ws>/review-items` | List workspace review items |
| `PUT` | `/api/review-items/<id>` | Update review item |

## Approvals

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/agent/approvals/pending` | Pending approvals |
| `GET` | `/api/agent/approvals/history` | Approval history |
| `POST` | `/api/agent/approvals/<id>/resolve` | Resolve approval |
| `GET` | `/api/agent/approvals/sse` | Approval SSE stream |

## Workspace

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workspaces` | List workspaces |
| `POST` | `/api/workspaces` | Create workspace |
| `GET` | `/api/workspaces/<ws>/state` | Workspace state |
| `GET` | `/api/workspaces/<ws>/status` | Workspace status |
| `DELETE` | `/api/workspaces/<ws>?confirm=true` | Delete non-default workspace |

## Security Notes

- Token auth is controlled by `NETWORK_AGENT_AUTH_ENABLED` and `NETWORK_AGENT_API_TOKEN`.
- Even when token auth is disabled for local desktop use, unsafe `/api/*` writes reject cross-origin browser requests.
- CMDB and Remote saved-device records do not persist plaintext device passwords.

## Misc

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Basic health check |
| `GET` | `/api/version` | Version info |
| `GET` | `/api/skills` | List skills |
| `GET` | `/api/harness/status` | Harness status |
