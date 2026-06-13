# Testing

## Backend

Run focused checks from the repo root:

```bash
./venv/bin/python -m pytest harness/test_loop_persistence.py harness/test_session_api_contract.py -q
```

Run RAG/context checks:

```bash
./venv/bin/python -m pytest harness/test_rag_context_foundation.py harness/test_rag_context_eval_script.py harness/test_retrieval_quality_v102.py -q
./venv/bin/python scripts/evaluate_rag_context.py
```

Run the full harness when broad regression coverage is needed:

```bash
./venv/bin/python -m pytest harness -q
```

Tool/skill/module wiring regressions:

```bash
./venv/bin/python -m pytest harness/test_tool_skill_module_design_regressions.py -q
```

Live LLM tests are gated and should only be enabled intentionally:

```bash
RUN_LIVE_TESTS=1 ./venv/bin/python -m pytest harness -q
```

## Frontend

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run typecheck
npm test -- --run
npm run build
npm run e2e
```

Current source contains:

- 15 Vitest files
- 12 Playwright E2E specs

## Source Fact Checks

Tool registry count:

```bash
./venv/bin/python - <<'PY'
from agent.runtime.services import default_runtime_services
svc = default_runtime_services()
reg = svc.tool_service.registry
print(len(reg.list_all()), len(reg.list_model_visible()))
PY
```

Expected current output: `76 75`.

Runtime capability count:

```bash
./venv/bin/python - <<'PY'
from agent.runtime.services import default_runtime_services
reg = default_runtime_services().capability_registry
print(len(reg.list_all()), len(reg.list_enabled()), len(reg.list_planned()))
PY
```

Expected current output: `7 4 3`.
