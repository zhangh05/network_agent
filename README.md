# Network Agent

Network Agent 是一个本地运行的网络工程 Agent 平台。当前版本由 Flask 后端、Codex-style Agent Runtime、React/Vite 前端、RAG 知识/记忆系统、工具运行时和 workspace 文件存储组成。

## Current Baseline

- Development head: **v3.0 clean canonical-only tool architecture**
- Backend: Flask app in `backend/main.py`
- Backend bind default: `0.0.0.0:8010`
- Frontend: React 18 + TypeScript + Vite 5 in `frontend/`
- Frontend dev port: `5173`
- Main agent endpoint: `POST /api/agent/message`
- Tool architecture: canonical-only
- Runtime tool registry: 98 canonical / 98 active

> **v3.0 hard reset**: Tool IDs are canonical-only. The planner
> exposes only `governance_status == 'active'` canonical tools. The
> public surface has no transition / retirement fields. handler_id
> is internal-only.

## What It Does

- Runs multi-turn network engineering conversations in the Workbench.
- Builds turn context from session history, workspace state, RAG knowledge, memory, artifacts, and registry metadata.
- Calls the configured LLM provider through a guarded runtime loop.
- Routes model tool calls through per-turn `ToolRouter` definitions using canonical tool_id, governance_status, capability_actions, risk, and approval metadata in every LLM tool description.
- Stores sessions, messages, runs, traces, artifacts, review items, knowledge sources, and reports under workspace-scoped storage.
- Provides a frontend for Workbench, Knowledge Library, Artifact Center, Review Center, Capability Matrix, Runtime Audit, and Settings.

## Current Source Layout

| Path | Purpose |
|---|---|
| `backend/` | Flask entrypoint and `/api/*` route groups |
| `agent/` | Agent app facade, session/turn runtime, LLM runtime, capability registries |
| `tool_runtime/` | canonical namespace, governance, capability actions, dispatch |
| `knowledge/` | Artifact-backed knowledge index, safe chunks, search |
| `memory/` | Durable memory store, redaction, RAG projection, conflict detection |
| `context/` | Context fragments, resolver, compressor, unified RAG retrieval |
| `artifacts/` | Artifact schemas, redaction, classification, workspace store |
| `workspace/` | Workspace, session, message, run, artifact persistence |
| `modules/` | Product modules and module registry |
| `skills/` | Skill registry and adapters |
| `frontend/` | React/Vite frontend |
| `harness/` | Backend and integration regression tests |
| `scripts/` | Catalog build/verify, audits, runtime gates, maintenance helpers |

## Tool Catalog

- Full v3.0 catalog: [docs/TOOL_CATALOG.md](docs/TOOL_CATALOG.md)
- Machine-readable: [reports/tool_catalog.json](reports/tool_catalog.json)
- Architecture contract: [docs/TOOL_ARCHITECTURE.md](docs/TOOL_ARCHITECTURE.md)
- Governance: [docs/TOOL_GOVERNANCE.md](docs/TOOL_GOVERNANCE.md)
- Identity contract: [docs/TOOL_CONTRACT.md](docs/TOOL_CONTRACT.md)

## Run Locally

## Local Python Rule

On this machine, use the installed local Python 3.12 directly. Do **not** create,
activate, or rely on `venv` / `.venv` unless a future task explicitly asks for an
isolated environment.

Expected interpreter:

```bash
python3 --version
```

Expected major/minor: `Python 3.12`.

Backend:

```bash
cd /Users/zhangh01/Desktop/network_agent
python3 backend/main.py --host 0.0.0.0 --port 8010
```

Frontend:

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev -- --host 0.0.0.0
```

Open:

- Vite dev app: `http://127.0.0.1:5173`
- Backend/static app: `http://127.0.0.1:8010`
- LAN/Tailscale access uses the host IP with the same ports.

## Key APIs

- `GET /api/health`
- `GET /api/version`
- `GET /api/runtime/summary`
- `POST /api/agent/message`
- `GET /api/sessions`
- `GET /api/sessions/<session_id>/messages`
- `GET /api/runs/recent` — supports `session_id` for current-session recent runs; includes `session_title` per run
- `GET /api/workspaces/<ws_id>/runs/<run_id>/trace`
- `POST /api/knowledge/upload`
- `GET /api/knowledge/sources`
- `GET /api/knowledge/search`
- `POST /api/memory/confirm`
- `GET /api/tools/catalog`
- `POST /api/tools/invoke`
- `POST /api/tools/dry-run`

## Safety Boundaries

- No real device access by default.
- No SSH, Telnet, SNMP, nmap, ping sweep, or config push exposed to the model.
- `config.push` remains forbidden.
- Planned capabilities are not callable.
- Pure chat, capability discovery, and business turns expose the curated primary model-visible tool catalog to the LLM as canonical names such as `workspace.file.read` and `host.shell.exec`.
- Every LLM-visible tool description includes canonical `tool_id`, `governance_status`, `risk`, `source`, and `approval` metadata so the model can choose tools with the safety context in view.
- High-risk runtime tools are model-visible but require explicit approval paths and allowlisted ids before execution.
- `POST /api/tools/invoke` is policy gated; high-risk tools require approved status before execution.
- Knowledge and memory snippets are redacted before being injected into context.
- Artifacts that may be deployable still require human review; the UI must not claim direct production readiness.

## LLM Configuration

- UI-managed provider settings are stored in `config/LLM_setting.json`.
- File fallback configuration uses `config/llm.yaml` and local ignored overrides in `config/llm.local.yaml`.
- The current local default provider path is OpenAI-compatible MiniMax with model `MiniMax-M3`.
- Real keys must come from environment variables, ignored local files, or the local settings UI; do not commit secrets.

## Useful Checks

Backend focused checks:

```bash
python3 -m pytest harness/test_loop_persistence.py harness/test_session_api_contract.py -q
```

RAG/context checks:

```bash
python3 -m pytest harness/test_rag_context_foundation.py harness/test_rag_context_eval_script.py -q
python3 scripts/evaluate_rag_context.py
```

Frontend checks:

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run typecheck
npm test -- --run
npm run build
```

Tool count fact check:

```bash
python3 - <<'PY'
from agent.runtime.services import default_runtime_services
from tool_runtime.tool_namespace import TOOL_NAMESPACE
svc = default_runtime_services()
reg = svc.tool_service.registry
print(len(reg.list_all()), len(reg.list_model_visible()), len(TOOL_NAMESPACE))
PY
```

Expected current output: `98 98 98`.

Namespace fact check:

```bash
python3 scripts/inspect_tool_namespace.py
```

Expected current output includes `canonical_count 98`, `active 98 tools`,
and `INSPECT TOOL NAMESPACE PASS`.

Tool architecture audit:

```bash
python3 scripts/audit_tool_architecture.py
python3 scripts/inspect_tool_architecture.py
```

Expected current output includes `canonical_count: 98`, `planner_visible_count: 98`,
`transition_statuses: 0`, and `PASS`.

Full v3.0 tool catalog: [docs/TOOL_CATALOG.md](docs/TOOL_CATALOG.md)
Machine-readable catalog: [reports/tool_catalog.json](reports/tool_catalog.json)

Catalog verification:

```bash
python3 scripts/build_tool_catalog.py
python3 scripts/verify_tool_catalog_doc.py
```

Expected current output for the verifier: `verify_tool_catalog_doc PASS`.

Latest local full harness evidence for this development head: `1042 passed, 7 skipped, 1 warning`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Runtime](docs/RUNTIME.md)
- [Capabilities and Tools](docs/CAPABILITIES_AND_TOOLS.md)
- [Tool Architecture](docs/TOOL_ARCHITECTURE.md)
- [Tool Governance](docs/TOOL_GOVERNANCE.md)
- [Tool Catalog](docs/TOOL_CATALOG.md) — full v3.0 tool catalog.
  Machine-readable mirror: [tool_catalog.json](reports/tool_catalog.json).
- [Knowledge and Memory](docs/KNOWLEDGE.md)
- [Frontend](docs/FRONTEND.md)
- [Operations](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Security](docs/SECURITY.md)
- [Retired Surfaces](docs/RETIRED_SURFACES.md)
- [Source-Derived Status](docs/SOURCE_DERIVED_STATUS.md)
