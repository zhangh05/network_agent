# Network Agent

Network Agent 是一个本地运行的网络工程 Agent 平台。当前版本由 Flask 后端、Codex-style Agent Runtime、React/Vite 前端、RAG 知识/记忆系统、工具运行时和 workspace 文件存储组成。

## Current Baseline

- Development head: v2.3 tool architecture optimization
- Latest release tag: `v2.1.3-hardening`
- Previous closure baseline: `v2.1.1-full-closure` (`b61a493`)
- Backend: Flask app in `backend/main.py`
- Backend bind default: `0.0.0.0:8010`
- Frontend: React 18 + TypeScript + Vite 5 in `frontend/`
- Frontend dev port: `5173`
- Main agent endpoint: `POST /api/agent/message`
- Runtime tool registry: **88 registered / 88 model-visible**
- Runtime capabilities: 7 total, 4 enabled, 3 planned
- Public `/api/capabilities`: runtime `CapabilityRegistry` projection, 7 total, 4 enabled, 3 planned

> **v2.3 development head**: v2.2 introduced the canonical namespace catalog
> layered over the stable 88 execution ids. v2.2.1 added multi-category
> `tool_chain` routing. v2.2.2 adds an intelligent planner with deterministic
> fallback, plan validation, and bounded candidate-tool exposure without
> changing the 88 execution-tool baseline. v2.3 adds governance status,
> capability actions, and audit reports so the planner reasons over stable
> capabilities instead of redundant historical tool fragments. See
> [docs/CAPABILITIES_AND_TOOLS.md](docs/CAPABILITIES_AND_TOOLS.md).

## What It Does

- Runs multi-turn network engineering conversations in the Workbench.
- Builds turn context from session history, workspace state, RAG knowledge, memory, artifacts, and registry metadata.
- Calls the configured LLM provider through a guarded runtime loop.
- Routes model tool calls through per-turn `ToolRouter` definitions using canonical category/group/action names with execution id, risk, source, and approval metadata in every LLM tool description.
- Stores sessions, messages, runs, traces, artifacts, review items, knowledge sources, and reports under workspace-scoped storage.
- Provides a frontend for Workbench, Knowledge Library, Artifact Center, Review Center, Capability Matrix, Runtime Audit, and Settings.

## Current Source Layout

| Path | Purpose |
|---|---|
| `backend/` | Flask entrypoint and `/api/*` route groups |
| `agent/` | Agent app facade, session/turn runtime, LLM runtime, capability registries |
| `tool_runtime/` | General tool catalog, policies, approvals, execution, audit metadata |
| `knowledge/` | Artifact-backed knowledge index, safe chunks, search |
| `memory/` | Durable memory store, redaction, RAG projection, conflict detection |
| `context/` | Context fragments, resolver, compressor, unified RAG retrieval |
| `artifacts/` | Artifact schemas, redaction, classification, workspace store |
| `workspace/` | Workspace, session, message, run, artifact persistence |
| `modules/` | Product modules and module registry |
| `skills/` | Skill registry and adapters |
| `frontend/` | React/Vite frontend |
| `harness/` | Backend and integration regression tests |
| `scripts/` | Audits, RAG evaluation, runtime gates, maintenance helpers |

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
- Every LLM-visible tool description includes canonical `tool_id`, `execution_tool_id`, `risk`, `source`, and `approval` metadata so the model can choose tools with the safety context in view.
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
svc = default_runtime_services()
reg = svc.tool_service.registry
print(len(reg.list_all()), len(reg.list_model_visible()))
PY
```

Expected current output: `88 88`.

Namespace fact check:

```bash
python3 scripts/inspect_tool_namespace.py
```

Expected current output includes `canonical_count 88`, `execution_count 88`, and `PASS`.
The same check also validates v2.2.1 multi-category route samples.
It also validates v2.3 governance, capability-action planning, deterministic planner, and validator samples.

Tool architecture audit:

```bash
python3 scripts/audit_tool_architecture.py
python3 scripts/inspect_tool_architecture.py
```

Expected current output includes `execution_count: 88`, `canonical_count: 88`,
`governance_conflicts: 0`, `planner_uses_deprecated: 0`, and `PASS`.

Latest local full harness evidence for this development head: `1317 passed, 12 skipped, 1 warning`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Runtime](docs/RUNTIME.md)
- [Capabilities and Tools](docs/CAPABILITIES_AND_TOOLS.md)
- [Tool Architecture](docs/TOOL_ARCHITECTURE.md)
- [Tool Governance](docs/TOOL_GOVERNANCE.md)
- [Knowledge and Memory](docs/KNOWLEDGE.md)
- [Frontend](docs/FRONTEND.md)
- [Operations](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Security](docs/SECURITY.md)
- [Retired Surfaces](docs/RETIRED_SURFACES.md)
- [Source-Derived Status](docs/SOURCE_DERIVED_STATUS.md)
