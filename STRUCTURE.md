# Current Project Structure

```text
network_agent/
├── agent/
│   ├── app/                    # AgentApp, session/thread orchestration
│   ├── capabilities/           # Business capability catalog only
│   ├── core/                   # Turn/session core types
│   ├── llm/                    # Provider config, runtime calls, key resolver
│   ├── modules/                # Domain implementations used by canonical tools
│   ├── prompts/                # Prompt templates
│   ├── runtime/                # TurnRunner, context pipeline, tools, durable state
│   ├── skills/                 # Skill metadata and skill.manage data source
│   └── tools/                  # Agent-facing router/registry adapter
├── artifacts/                  # Artifact records and content store
├── backend/
│   ├── main.py                 # Flask app entry
│   ├── api/                    # REST routes
│   ├── core/                   # Auth, limits, settings, response helpers
│   └── ws/                     # WebSocket gateways
├── config/                     # Local provider/runtime config; secrets ignored
├── data/                       # Local runtime JSON/JSONL stores
├── docs/                       # Current architecture and API docs
├── frontend/                   # React 18 + TypeScript + Vite app
├── harness/                    # Backend contract/architecture tests
├── jobs/                       # Job records, lifecycle, runner, worker
├── observability/              # Trace/event persistence
├── prompts/                    # Top-level prompt templates and registry
├── reports/                    # Generated reports; audits are ignored unless tracked
├── runtime/                    # Diagnostics/selfcheck utilities
├── storage/                    # File store abstractions
├── tool_runtime/               # 21 canonical tools, manifest, policy, executor
├── workspace/                  # Workspace/session/run/message/memory stores
├── workspaces/                 # Local workspace data; not committed
├── start.sh
└── stop.sh
```

## Ownership Rules

- Tool execution belongs to `tool_runtime/`.
- Business capability descriptions belong to `agent/capabilities/catalog.py`.
- Durable runtime state belongs to `agent/runtime/durable/`.
- User-visible workbench state belongs to `frontend/src/stores/`.
- Persistent local user data belongs under `workspaces/`, `data/`, `config/providers/`, or `logs/` and must stay out of Git.

## Removed Concepts

The current tree does not use tool aliases, compatibility shims, generated module capability registries, or multiple approval stores. Do not reintroduce them.
