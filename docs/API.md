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
| `POST` | `/api/tools/dry-run?workspace_id=<ws>` | Tool dry-run metadata |
| `GET` | `/api/capabilities` | Business capability catalog |

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
| `GET` | `/api/workspaces/<ws>/artifacts?evidence_view=current\|history\|deliverables` | Managed artifacts with evidence authority projection |
| `GET` | `/api/workspaces/<ws>/artifacts/<artifact_id>` | Artifact metadata, lineage, and authority status |
| `GET` | `/api/memory/search?workspace_id=<ws>` | Search active memories |
| `POST` | `/api/memory/write` | Write memory through MemoryWriteGate |
| `GET` | `/api/cmdb/assets?workspace_id=<ws>` | Device assets |
| `POST` | `/api/cmdb/assets` | Save device asset |
| `GET` | `/api/remote/devices?workspace_id=<ws>` | Remote devices |
| `POST` | `/api/remote/connect` | Connect to remote device |

Inspection artifacts form immutable evidence streams keyed by CMDB asset and
script profile. The newest complete observation is the current authoritative
evidence. A partial observation is provisional only when the stream has never
completed successfully; incomplete observations never replace a complete one.
Baselines, incidents, changes, and scheduled checks retain their exact task and
artifact IDs even after a newer observation becomes authoritative.

## Inspection

CMDB-driven inspection runs only fixed read-only scripts selected by each asset's vendor and device type. The runner resolves device credentials server-side through `exec.run(asset_id=...)`; request and response schemas never include password fields. Users do not choose inspection templates.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/inspection/tasks` | Run an automatic inspection for a CMDB scope |
| `GET` | `/api/inspection/tasks?workspace_id=<ws>&limit=<n>` | List recent inspection tasks |
| `GET` | `/api/inspection/tasks/<task_id>?workspace_id=<ws>` | Inspection task detail |
| `POST` | `/api/inspection/tasks/<task_id>/cancel` | Cancel inspection task when supported |
| `GET` | `/api/inspection/tasks/<task_id>/report?workspace_id=<ws>&format=md` | Render Markdown, JSON, or HTML report metadata |
| `GET` | `/api/inspection/tasks/<task_id>/report.html?workspace_id=<ws>` | Open the HTML inspection report directly |

## Network Assurance

Network Assurance derives state from CMDB identity and completed inspection evidence. It stores no credentials, does not execute configuration changes, and marks incomplete inspection comparisons as `partial` rather than inventing removed state.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/assurance/overview?workspace_id=<ws>` | Current assurance health and counts |
| `GET/POST` | `/api/assurance/baselines` | List or create a complete-evidence baseline |
| `POST` | `/api/assurance/checks` | Start a fresh inspection-backed baseline check (202) |
| `GET` | `/api/assurance/checks?workspace_id=<ws>` | List and refresh baseline check tasks |
| `GET` | `/api/assurance/checks/<check_id>?workspace_id=<ws>` | Track collection progress and final drift ID |
| `GET` | `/api/assurance/drifts?workspace_id=<ws>` | List drift records |
| `GET` | `/api/assurance/topology?workspace_id=<ws>` | Latest evidence-backed topology |
| `POST` | `/api/assurance/topology/build` | Start a fresh inspection-backed topology refresh (202) |
| `POST` | `/api/assurance/topology/impact` | Start fresh evidence collection and impact analysis (202) |
| `GET` | `/api/assurance/operations[/<id>]` | List or track topology, impact, incident, and change operations |
| `GET/POST/PATCH` | `/api/assurance/incidents[...]` | Start and manage evidence-collecting investigations |
| `GET/POST` | `/api/assurance/changes` | List or create non-deploying change plans |
| `POST` | `/api/assurance/changes/<id>/validate` | Start the real pre-change inspection (202) |
| `POST` | `/api/assurance/changes/<id>/postcheck` | Start post-change inspection and compare with pre-change state (202) |
| `GET/POST/PATCH` | `/api/assurance/schedules[...]` | Manage recurring inspection-and-drift checks |
| `POST` | `/api/assurance/schedules/<id>/run` | Run a scheduled check immediately (202) |

## Error Shape

```json
{ "ok": false, "error": "invalid_workspace_id" }
```

Successful responses include `{"ok": true, ...}` unless the route is a streaming endpoint.
# Managed Storage

- `GET /api/storage/files?workspace_id=<id>` returns active FileRecord projections without physical paths.
- `GET /api/storage/events?workspace_id=<id>` streams workspace-scoped `storage_changed` events for frontend synchronization.
