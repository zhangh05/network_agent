# Network Agent

AI-powered network analysis agent with general coding capabilities. Analyzes PCAPs, translates configs, builds topologies, manages CMDB, operates remote devices via SSH/Telnet, and supports Git/code search/browser automation — through a conversational interface.

## Architecture (v3.9)

See [STRUCTURE.md](STRUCTURE.md) for complete directory reference and [DESIGN.md](DESIGN.md) for pipeline design.

### Security boundaries

- **Unified ApprovalStore** (`agent/approval.py`) — single source of truth for all tool approval. No dual-store or legacy fallback.
- **Unified tool execution** — all tool dispatch goes through `ActionExecutor` → `ToolDispatcher` → `ToolRouter`. No bypass or direct handler dispatch.
- **Workspace isolation** — empty/invalid workspace_id returns 400; no implicit "default" fallback.
- **Admin boundary** — approval resolve requires `X-Admin-Token` when `NETWORK_AGENT_ADMIN_TOKEN` is set; otherwise localhost only.
- **Confirm requirement** — all destructive operations (archive/retention apply) require server-side `confirm=True`.

### Key capabilities (10 total, 8 enabled)

| Capability | Status | Tools |
|-----------|--------|-------|
| knowledge | enabled | knowledge.search, knowledge.chunk.*, knowledge.source.* |
| artifact_management | enabled | workspace.artifact.* |
| review_flow | enabled | review.item.* |
| device | enabled | device.add, device.get, device.list, device.delete |
| exec | enabled | exec.run (ssh/telnet/local), exec.python, exec.slash |
| pcap_analysis | enabled | pcap.analysis.run |
| coding | enabled | git.status/diff/log/commit/push, code.search |
| browser | enabled | browser.navigate, browser.extract |
| topology | planned | — |
| inspection | planned | — |

### Tool system (73 tools, 13 categories)

```text
host(4) workspace(23) knowledge(12) web(7) network(4)
runtime(13) memory(8) report_data(13) agent(6) cmdb(4)
git(5) code(1) browser(2)
```

20 core tools always visible via CORE_TOOL_IDS. Remaining tools activated by scene-aware ToolPlannerV2.

## API

Core endpoints:
- `POST /api/agent/message` — Main agent entry
- `WS /ws/agent` — Real-time streaming
- `POST /api/tools/invoke` — Execute any tool
- `GET /api/capabilities` — List capabilities
- `GET /api/health` — Health check

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask + Python 3.12+ |
| Frontend | React + TypeScript + Vite |
| LLM | MiniMax M3 (245K context) |
| Retrieval | BM25 + CJK bigram/trigram |
| Storage | JSONL (append + tombstone + GC) |
| Term | xterm.js (SSH/Telnet) |
