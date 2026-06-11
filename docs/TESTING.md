# Testing

## Backend

Run focused checks from the repo root:

```bash
./venv/bin/python -m pytest harness/test_loop_persistence.py harness/test_session_api_contract.py -q
```

Run the full harness when you need broad regression coverage:

```bash
./venv/bin/python -m pytest harness -q
```

Live LLM tests are gated and should only be enabled intentionally:

```bash
RUN_LIVE_TESTS=1 ./venv/bin/python -m pytest harness -q
```

## Frontend

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run typecheck
npm run test
npm run build
npm run e2e
```

Current source contains 12 Vitest files and 11 Playwright E2E specs.

## Source Fact Checks

Useful quick checks:

```bash
./venv/bin/python - <<'PY'
from agent.runtime.services import default_runtime_services
svc = default_runtime_services()
reg = svc.tool_service.registry
print(len(reg.list_all()), len(reg.list_model_visible()))
PY
```

Expected current output: `73 70`.
