# Session Management

Network Agent v3.1 introduces **Conversation Sessions** — a way to group multiple
Agent runs into persistent chat threads that survive browser refreshes and
workspace switches.

## Overview

| Feature | Status | Notes |
|---|---|---|
| Session creation | ✅ | Auto-created on first message, or via "+" button |
| Session list | ✅ | Active sessions shown in Agent Panel dropdown |
| Session switching | ✅ | Click any session to load its message history |
| Auto-restore on load | ✅ | Page refresh restores current session messages |
| Auto-title | ✅ | First user input becomes the session title |
| Archive | ✅ | Soft archive — session hidden from active list |
| Soft delete | ✅ | Marked deleted — run records preserved for audit |
| Permanent delete | ✅ | Requires `?confirm=true` — only deletes session metadata |
| Workspace isolation | ✅ | Sessions are scoped per workspace |
| Run association | ✅ | Every run with `session_id` is auto-linked |

## Data Model

```python
Session {
  session_id:    str   # 16-char hex UUID
  workspace_id:  str   # e.g. "default"
  title:         str   # Auto-generated from first input
  status:        str   # active | archived | deleted
  created_at:    str   # ISO 8601 UTC
  updated_at:    str   # ISO 8601 UTC
  run_ids:       List[str]  # Ordered run associations
  metadata:      Dict       # Extensible metadata
}
```

## Architecture

```
Frontend (index.html)
  ├── localStorage: na_workspace_id, na_current_session_id, na_ui_prefs
  ├── Session Bar: title + "+" (new) + "☰" (list toggle)
  ├── Session List: active sessions with ⋮ menu (archive/delete)
  └── Chat Panel: messages loaded from /api/sessions/<id>/messages

Backend
  ├── workspace/session_store.py   # Session CRUD + message recovery
  ├── agent/state.py               # NetworkAgentState.session_id
  ├── agent/graph.py               # run_agent(session_id=...)
  ├── workspace/run_store.py       # Auto-associate run → session
  └── backend/api/session_routes.py # REST API

Persistence
  ├── workspaces/<ws>/sessions/<sid>.json   # Session metadata
  └── workspaces/<ws>/runs/<rid>.json       # Run records (unchanged)
```

## API Reference

### Create Session
```
POST /api/sessions
Body: {"workspace_id": "default", "title": "My Session", "metadata": {}}
Response: {"ok": true, "session": {...}}
```

### List Sessions
```
GET /api/sessions?workspace_id=default&status=active&limit=50
Response: {"ok": true, "sessions": [...], "counts": {"active": N, ...}}
```

Status filter: `active`, `archived`, `deleted`. Omit for all non-deleted.

### Get Session + Messages
```
GET /api/sessions/<session_id>?workspace_id=default&include_messages=1
Response: {"ok": true, "session": {...}, "messages": [...]}
```

Messages format:
```json
[
  {"role": "user", "content": "...", "created_at": "...", "run_id": "..."},
  {"role": "assistant", "content": "...", "created_at": "...", "run_id": "...", "metadata": {...}}
]
```

### Update Session
```
PUT /api/sessions/<session_id>?workspace_id=default
Body: {"title": "New Title", "status": "active", "metadata": {...}}
```

### Archive
```
POST /api/sessions/<session_id>/archive?workspace_id=default
```

### Restore
```
POST /api/sessions/<session_id>/restore?workspace_id=default
```

### Soft Delete
```
POST /api/sessions/<session_id>/soft-delete?workspace_id=default
```

### Permanent Delete
```
DELETE /api/sessions/<session_id>?workspace_id=default&confirm=true
```

**⚠️ Safety:** Without `confirm=true`, returns 400 with `error: confirm_required`.
Run records and artifacts are **never** deleted — only the session metadata file.

### Default Session
```
GET /api/sessions/default?workspace_id=default
```
Returns the most recent active session, or creates one if none exist.

### Agent Run with Session
```
POST /api/agent/run
Body: {"message": "...", "workspace_id": "default", "session_id": "..."}
```

If `session_id` is provided, the run is automatically associated with the
session and the session title is auto-updated from the first user input.

## Deletion Semantics

| Action | What happens | Run records | Artifacts | Recoverable |
|---|---|---|---|---|
| Archive | Status → `archived` | Preserved | Preserved | ✅ Restore |
| Soft Delete | Status → `deleted` | Preserved | Preserved | ✅ Restore |
| Permanent Delete | Session `.json` removed | Preserved | Preserved | ❌ |

**First version design principle:** Never physically delete runs or artifacts.
Sessions are lightweight grouping metadata. Audit trail is preserved.

## localStorage Role

| Key | Purpose | Example |
|---|---|---|
| `na_workspace_id` | Current workspace | `"default"` |
| `na_current_session_id` | Current session ID | `"abc123..."` |
| `na_settings` | UI preferences (lang, theme, font size) | `{ui_lang: "zh", ...}` |

**Removed from localStorage:** Chat history, message content, run results.
All chat state is loaded from the backend on page load.

## Frontend Behavior

1. **Page load:**
   - Read `na_workspace_id` and `na_current_session_id` from localStorage
   - Call `/api/sessions/default` if no saved session ID
   - Call `/api/sessions/<id>?include_messages=1` to load chat history
   - Render messages into `#ag-body`

2. **New message:**
   - If no `current_session_id`, auto-create session via POST `/api/sessions`
   - Send message with `session_id` to `/api/agent/run`
   - Append user bubble immediately, then AI bubble on response

3. **New session:**
   - Click "+" → POST `/api/sessions` → switch to new session

4. **Switch session:**
   - Click session title or "☰" → show list → click item → load messages

5. **Workspace switch:**
   - Clears `na_current_session_id` → reload picks default for new workspace

## Testing

```bash
# Session store unit tests
python harness/test_session_management.py

# API contract tests
venv/bin/python harness/test_session_api_contract.py
```

Total coverage: 23 store tests + 12 API contract tests = 35 tests.
