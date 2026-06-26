# Frontend Reference

Current frontend architecture (v3.9).

## Pages & Routes

11 navigation items routing to 14 page components (`frontend/src/app/App.tsx`):

| Route | Page | Layout | Purpose |
|-------|------|--------|---------|
| `/workbench` | AgentWorkbench | 3-col | Chat, session list, inspector |
| `/packet` | PacketAnalysis | 2-col | PCAP upload and analysis |
| `/runs` | RunsPage | 2-col | Per-session run trace/decision debug |
| `/capabilities` | CapabilityCenter | 2-col | Capability manifest catalog |
| `/jobs` | JobsPage | 2-col | Session-level job tracking (3 tabs: runs, artifacts, stats) |
| `/knowledge` | KnowledgeLibrary | 2-col | Knowledge source management |
| `/artifacts` | ArtifactCenter | 2-col | Artifact browse and preview |
| `/memory` | MemoryPage | 2-col | Memory CRUD |
| `/cmdb` | CMDBPage | 2-col | Device asset inventory |
| `/diagnostics` | Diagnostics | 1-col | System diagnostics (cached, manual trigger) |
| `/settings` | Settings | 2-col | LLM provider config |

### Removed routes
`/files` (FileManager), `/audit` (RuntimeAudit), `/reviews` (ReviewCenter) were removed from navigation. Their page components remain in the codebase but are not routed.

## Data Sources

| Page | Primary API | Key data |
|------|------------|----------|
| AgentWorkbench | `POST /api/agent/message`, `WS /ws/agent` | `final_response`, events |
| PacketAnalysis | `POST /api/pcap/parse`, `GET /api/pcap/session/<id>` | PCAP sessions |
| RunsPage | `GET /api/runs/recent?session_id=<id>` | `runs[]`, trace events, decision report |
| JobsPage | `GET /api/jobs?workspace_id=<id>` | `jobs[]`, run_ids, artifacts |
| Diagnostics | `GET /api/runtime/health`, `/selfcheck`, `/agent/usage` | Health, usage, prompts, retention |
| ArtifactCenter | `GET /api/workspaces/<ws>/artifacts` | Artifact list |
| MemoryPage | `GET /api/memory/list`, `POST /api/memory/delete` | Memory records |
| KnowledgeLibrary | `GET /api/knowledge/*` | Knowledge sources |
| CapabilityCenter | `GET /api/capabilities` | Capability manifests |
| CMDBPage | `GET /api/cmdb/assets` | Device assets |
| Settings | `GET/POST /api/agent/llm/config` | LLM configuration |

## Streaming

- HTTP event replay: `POST /api/agent/message` with `stream_mode=event_replay` returns SSE.
- WebSocket live: `WS /ws/agent` pushes `{type: "token", content: "..."}` in real time.

## Key Principles

- `final_response` (string) is the primary UI content source — NOT `final_response.content`.
- Backend metadata (`truth_report`, `stability_report`, `turn_trace`) lives in `ctx.metadata` but may not be in API response. Use `/api/runs/*/decision` for decision reports.
- No hard-coded tool counts or capability counts in UI — read from backend truth source.
