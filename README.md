# Network Agent

AI-powered network analysis agent. Analyzes PCAPs, translates configs, builds topologies, and performs network diagnostics through conversational interface.

## Quick Start

```bash
# Backend (port 8010)
python backend/main.py --host 0.0.0.0 --port 8010

# Frontend (port 5173)
cd frontend && npm run dev
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full architecture reference.

Key modules:
- `agent/` — Core agent loop, LLM provider, app service
- `agent/runtime/` — Turn pipeline: ContextPipeline (13 stages) → TurnRunner → ToolExecutionPipeline (9 stages) → hooks
- `backend/` — Flask API with 50+ endpoints, WebSocket streaming
- `frontend/` — React/TS + Vite, 10 nav items, 12 pages
- `tools/` — Tool runtime with canonical registry
- `memory/` — Memory store with JSONL-backed CRUD
- `jobs/` — Session-level job tracking with run accumulation
- `artifacts/` — Artifact storage with per-run indexing

## API

See [docs/API.md](docs/API.md) for complete API reference.

Core endpoints:
- `POST /api/agent/message` — Main agent entry
- `WS /ws/agent` — Real-time streaming
- `GET/POST /api/sessions` — Session management
- `GET /api/jobs` — Job management
- `GET /api/runs/recent` — Run history

## Frontend

See [docs/FRONTEND.md](docs/FRONTEND.md) for frontend reference.

Pages: Workbench, PacketAnalysis, Runs, Capabilities, Jobs, Knowledge, Artifacts, Memory, Diagnostics, Settings.

## Runtime

See [docs/RUNTIME.md](docs/RUNTIME.md) for runtime execution model.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask + Python 3.13 |
| Frontend | React + TypeScript + Vite |
| LLM | MiniMax M3 (245K context) |
| Retrieval | BM25 + CJK bigram/trigram |
| Storage | JSONL (append + tombstone + GC) |
