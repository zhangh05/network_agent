# Agent Handoff Notes

## Local Runtime

- Use the repo at `/Users/zhangh01/Desktop/network_agent`.
- Use the installed local `python3` directly; expected version is Python 3.12.
- Do not create, activate, or depend on `venv` / `.venv` for normal service
  startup, tests, or source review.
- Start the backend with:

```bash
cd /Users/zhangh01/Desktop/network_agent
python3 backend/main.py --host 0.0.0.0 --port 8010
```

- Run backend tests with:

```bash
python3 -m pytest harness -q
```

- Frontend commands run from `frontend/`:

```bash
npm run typecheck
npm test -- --run
npm run dev -- --host 0.0.0.0
```

## Current UI State Contract

- Workbench hierarchy is `workspace -> session -> recent runs`.
- Changing the workspace must refresh the session list.
- Changing the active session must refresh recent runs with `session_id`.
- Archived/deleted sessions are excluded from the Workbench session list and
  sidebar recent runs.
- Runtime Audit can still request all sessions with `session_status=`.
