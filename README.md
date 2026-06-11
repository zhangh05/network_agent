# Network Agent

Network Agent 是一个运行在本机的网络工程 Agent 平台。当前源码由 Flask 后端、Codex-style Agent Runtime、React/Vite 前端、工具运行时和 workspace 文件存储组成。

## Current Source Baseline

- Backend: Flask app in `backend/main.py`
- Default backend port: `8010`
- Frontend: React 18 + TypeScript + Vite 5 in `frontend/`
- Default frontend dev port: `5173`
- Main agent endpoint: `POST /api/agent/message`
- Legacy-compatible endpoint: `POST /api/agent/run`
- Runtime tool registry: **73 registered / 70 model-visible**
- Runtime capabilities: 7 total, 4 enabled, 3 planned
- Public `/api/capabilities`: YAML registry projection, 5 total, 3 enabled, 2 planned

The detailed source-derived status is in [docs/SOURCE_DERIVED_STATUS.md](docs/SOURCE_DERIVED_STATUS.md).

## Run Locally

```bash
cd /Users/zhangh01/Desktop/network_agent
./venv/bin/python backend/main.py --port 8010
```

For frontend development:

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev
```

Open:

- Backend/static app: `http://127.0.0.1:8010`
- Vite dev app: `http://127.0.0.1:5173`

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Runtime](docs/RUNTIME.md)
- [Capabilities and Tools](docs/CAPABILITIES_AND_TOOLS.md)
- [Frontend](docs/FRONTEND.md)
- [Knowledge](docs/KNOWLEDGE.md)
- [Operations](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Security](docs/SECURITY.md)

## Important Safety Boundaries

- No real device access by default.
- No SSH, Telnet, SNMP, nmap, ping sweep, or config push exposed to the model.
- `config.push` remains forbidden.
- Planned capabilities are not callable.
- High-risk runtime tools are disabled and require explicit approval paths.

## Useful Commands

```bash
# Backend focused checks
./venv/bin/python -m pytest harness/test_loop_persistence.py harness/test_session_api_contract.py -q

# Frontend checks
cd frontend
npm run typecheck
npm run test
npm run build
```
