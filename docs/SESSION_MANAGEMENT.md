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

## 7. Chat history persistence (plan-C, v1.0.2+)

v1.0.2 起，workbench chat 历史走 **plan-C 方案**：localStorage 兜底 + 后端 background fetch merge。

### 7.1 双层存储

| 层 | 位置 | 作用 | 失效 |
|---|---|---|---|
| **L1 本地** | `localStorage["na_workbench"]` (zustand persist) | 切会话 / F5 刷新即时恢复 (0ms) | 清浏览器数据 / 切设备 |
| **L2 服务端** | `GET /api/sessions/<id>/messages` → `workspace.run_store` + `session_store.run_ids` | 跨设备 / 跨 tab 同步 | 后端 run 记录丢失 |

### 7.2 run 落盘的关键路径（v1.0.2 fix）

**Bug**：v0.6+ 新 runtime `agent/runtime/loop.py` 用 dataclass-based `Turn/Session/TurnContext`，跟 legacy `NetworkAgentState` 字段对不上，所以 `write_run_record()` 一次都没被调用。4 个 return 出口（success / provider_error / timeout / max_steps）都没落盘 → `session.run_ids` 永远 `[]` → `/api/sessions/<id>/messages` 永远 `[]` → 前端 background fetch 永远空。

**Fix**（`agent/runtime/loop.py::run_turn`）：
- 加 `_persist_run_record(session, turn, result, context)` adapter，把 dataclass 字段投影成 `SimpleNamespace`，让 `write_run_record()` 能识别。
- 4 个 return 出口（`AgentResult(ok=False/True, ...)`）前各调一次。
- try/except 包裹 — 持久化失败**不**会炸 turn。
- 失败也是历史（failed turn 也落盘）。

### 7.3 `get_session_messages` 端点

```
GET /api/sessions/<session_id>/messages?workspace_id=default
→ {
  "ok": true,
  "count": <int>,
  "messages": [
    { "role": "user" | "assistant" | "system",
      "content": "...",
      "created_at": "<iso>",
      "run_id": "...",
      "intent": "...", "status": "...", "capability": "...",
      "trace_id": "...", "quality_summary": {...}, "llm_metadata": {...} },
    ...
  ]
}
```

实现：遍历 `session.run_ids`，每个 run 拆 2 条 (user_input_summary → user, final_response_summary → assistant)。前端 `useWorkbenchStore.mergeFromBackend(sid, msgs)` 按 `created_at` 升序 dedup 合并不删本地。

### 7.4 前端 localStorage 数据结构

```ts
// frontend/src/stores/workbench.ts
interface WorkbenchState {
  bySession: Record<string, ChatMsg[]>;  // 持久化: key=session_id, value=消息列表
  currentSessionId: string | null;       // 不持久化 (走 useSessionStore["na_session"])
  history: ChatMsg[];                    // 派生: bySession[currentSessionId]
  latestResult: AgentResult | null;      // Inspector 用
  sending: boolean;                      // 派生
  // ...
}
```

容量限制：
- 每 session 最多 **30 条** (LRU 切片, 留最新 30)
- 全局最多 **5 个 session** (按 session_id 字典序 LRU 淘汰)
- 无 session 时的消息走 `_scratch` 池，等后端返回 `session_id` 后由 AgentWorkbench 迁移

### 7.5 时序

```
切会话 / F5 刷新
   ↓
1) switchSession → 即时从 bySession 渲染 (0ms, 不等网络)
   ↓
2) 后台 sessionsApi.messages(sid, ws_id) → 拉到 msgs
   ↓
3) mergeFromBackend(sid, msgs) → 按 created_at 升序, dedup, 不删本地
   ↓
4) 渲染最终结果

发送一条消息
   ↓
1) appendUser(text, sid) → _scratch 池 (若 sid=null)
   ↓
2) POST /api/agent/message (后端可能自动建 session)
   ↓
3) 收到 res.session_id → 把 _scratch 池迁过去
   ↓
4) appendAssistant → 落 bySession[sid] + 持久化
   ↓
5) 再 background fetch /messages 一次 (触发跨设备同步)
```

### 7.6 测试

- `harness/test_loop_persistence.py` (3 case) — 后端 _persist_run_record 行为
- `frontend/src/test/workbenchPersist.test.tsx` (8 case) — 前端 store 行为
- `e2e/11-workbench-persistence.spec.ts` (1 case) — F5 刷新后历史仍在

Gates: 348 harness passed / 21 vitest / 11 e2e（详见 `RELEASE_HISTORY.md`）。
