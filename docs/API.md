# API

Base URL: `http://localhost:8010`

All workspace-scoped endpoints require an explicit valid `workspace_id`. Missing workspace IDs return 400.

## Agent

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/agent/message` | Run one user turn over HTTP/SSE style response |
| `GET` | `/api/agent/sse/stream/<session_id>?workspace_id=<ws>` | Subscribe to session runtime events |
| `WS` | `/ws/agent` | WebSocket conversation stream |

## Runtime

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/runtime/summary` | Capability/tool counts |
| `GET` | `/api/runtime/health?workspace_id=<ws>` | Runtime health |
| `GET` | `/api/runtime/selfcheck?workspace_id=<ws>` | Runtime selfcheck |
| `GET` | `/api/runtime/tasks?workspace_id=<ws>&session_id=<id>` | List durable tasks |
| `GET` | `/api/runtime/tasks/<task_id>?workspace_id=<ws>` | Task detail |
| `GET` | `/api/runtime/tasks/<task_id>/events?workspace_id=<ws>` | Task events |
| `GET` | `/api/runtime/tasks/<task_id>/checkpoints?workspace_id=<ws>` | Task checkpoints |
| `POST` | `/api/runtime/tasks/<task_id>/cancel?workspace_id=<ws>` | Cancel task |
| `POST` | `/api/runtime/tasks/<task_id>/resume?workspace_id=<ws>` | Resume task |
| `POST` | `/api/runtime/tasks/<task_id>/steps/<step_id>/retry?workspace_id=<ws>` | Retry safe failed step |

## Tools And Capabilities

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/tools/invoke` | Invoke one canonical tool through ToolRuntimeClient |
| `GET` | `/api/tools/history?workspace_id=<ws>` | Tool invocation history |
| `GET` | `/api/tools/dry-run?workspace_id=<ws>` | Tool dry-run metadata |
| `GET` | `/api/capabilities` | Business capability catalog |
| `GET` | `/api/modules` | Module display metadata |

## Approval

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/agent/approvals/pending?workspace_id=<ws>` | Pending approvals |
| `GET` | `/api/agent/approvals/history?workspace_id=<ws>` | Approval history |
| `GET` | `/api/agent/approvals/sse?workspace_id=<ws>` | Approval event stream |
| `POST` | `/api/agent/approvals/<approval_id>/resolve` | Resolve approval decision |

Approval requests are durable interrupts. Approval is required only when policy marks an action high-risk or destructive.

## Workspace Data

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/sessions?workspace_id=<ws>` | Session list |
| `GET` | `/api/sessions/<session_id>/messages?workspace_id=<ws>` | Session messages |
| `POST` | `/api/sessions/<session_id>/restore?workspace_id=<ws>` | Restore archived session |
| `GET` | `/api/runs/recent?workspace_id=<ws>&session_id=<id>` | Recent runs |
| `GET` | `/api/memory/search?workspace_id=<ws>` | Search active memories |
| `POST` | `/api/memory/write` | Write memory through MemoryWriteGate |
| `GET` | `/api/cmdb/assets?workspace_id=<ws>` | Device assets |
| `POST` | `/api/cmdb/assets` | Save device asset |
| `GET` | `/api/remote/devices?workspace_id=<ws>` | Remote devices |
| `POST` | `/api/remote/connect` | Connect to remote device |

## Error Shape

```json
{ "ok": false, "error": "invalid_workspace_id" }
```

Successful responses include `{"ok": true, ...}` unless the route is a streaming endpoint.
