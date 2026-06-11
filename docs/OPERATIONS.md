# Operations

## Start Backend

```bash
cd /Users/zhangh01/Desktop/network_agent
./venv/bin/python backend/main.py --port 8010
```

## Start Frontend Dev Server

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev
```

## Health Checks

```bash
curl http://127.0.0.1:8010/api/health
curl http://127.0.0.1:8010/api/runtime/health
curl http://127.0.0.1:8010/api/tools/catalog
```

## Runtime Maintenance

Runtime maintenance endpoints include:

- `GET /api/runtime/selfcheck`
- `GET /api/workspaces/<ws_id>/selfcheck`
- `GET /api/workspaces/<ws_id>/retention/preview`
- `POST /api/workspaces/<ws_id>/retention/apply`
- `GET /api/workspaces/<ws_id>/archive/preview`
- `POST /api/workspaces/<ws_id>/archive/apply`

## Configuration

- LLM config routes: `/api/agent/llm/config`
- Example configs: `config/llm.example.yaml`, `config/LLM_setting.example.json`
- Local configs are machine-specific and should not be treated as docs.
