# Operations

## Start Backend

```bash
cd /Users/zhangh01/Desktop/network_agent
./venv/bin/python backend/main.py --host 0.0.0.0 --port 8010
```

The backend also serves the built/static frontend through Flask.

## Start Frontend Dev Server

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev -- --host 0.0.0.0
```

Default local URLs:

- `http://127.0.0.1:8010`
- `http://127.0.0.1:5173`

## Health Checks

```bash
curl http://127.0.0.1:8010/api/health
curl http://127.0.0.1:8010/api/runtime/health
curl http://127.0.0.1:8010/api/runtime/summary
curl http://127.0.0.1:8010/api/tools/catalog
```

## Runtime Maintenance

Maintenance endpoints are workspace-scoped and expose preview/apply flows:

- `GET /api/runtime/selfcheck`
- `GET /api/workspaces/<ws_id>/selfcheck`
- `GET /api/workspaces/<ws_id>/retention/preview`
- `POST /api/workspaces/<ws_id>/retention/apply`
- `GET /api/workspaces/<ws_id>/archive/preview`
- `POST /api/workspaces/<ws_id>/archive/apply`

Use preview endpoints before apply endpoints.

## LLM Configuration

- Status: `GET /api/agent/llm/status`
- Test: `POST /api/agent/llm/test`
- Config: `GET/POST/DELETE /api/agent/llm/config`
- Example files: `config/llm.example.yaml`, `config/LLM_setting.example.json`

Local config files are machine-specific and should not be treated as docs.

## Runtime Files

Operational files may change while the service runs:

- `workspaces/_runtime/llm_recent_failure.json`
- `workspaces/_runtime/llm_recent_success.json`
- `logs/*.log`
- workspace session/run/artifact/index files

Do not include those runtime changes in documentation commits unless the task explicitly asks to preserve runtime state.

## Cleanup

Safe generated directories:

```bash
find . -type d -name __pycache__ -not -path './venv/*' -not -path './frontend/node_modules/*' -prune -exec rm -rf {} +
rm -rf .pytest_cache frontend/dist frontend/test-results
```

Do not delete `workspaces/`, `memory/data/`, or `data/` unless intentionally resetting local runtime state.
