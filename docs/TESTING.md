# Testing

## Local Python Rule

Use the local `python3` interpreter directly. On this machine it is expected to
be Python 3.12. Do not create, activate, or depend on `venv` / `.venv` for normal
development, testing, or service startup.

```bash
python3 --version
```

## Backend

Run focused checks from the repo root:

```bash
python3 -m pytest harness/test_loop_persistence.py harness/test_session_api_contract.py -q
```

Run RAG/context checks:

```bash
python3 -m pytest harness/test_rag_context_foundation.py harness/test_rag_context_eval_script.py harness/test_retrieval_quality_v102.py -q
python3 scripts/evaluate_rag_context.py
```

Run the full harness when broad regression coverage is needed:

```bash
python3 -m pytest harness -q
```

Tool/skill/module wiring regressions:

```bash
python3 -m pytest harness/test_tool_skill_module_design_regressions.py -q
```

Live LLM tests are gated and should only be enabled intentionally:

```bash
RUN_LIVE_TESTS=1 python3 -m pytest harness -q
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
python3 - <<'PY'
from agent.runtime.services import default_runtime_services
svc = default_runtime_services()
reg = svc.tool_service.registry
print(len(reg.list_all()), len(reg.list_model_visible()))
PY
```

Expected current output: `58 57`.

Runtime capability count:

```bash
python3 - <<'PY'
from agent.runtime.services import default_runtime_services
reg = default_runtime_services().capability_registry
print(len(reg.list_all()), len(reg.list_enabled()), len(reg.list_planned()))
PY
```

Expected current output: `7 4 3`.
