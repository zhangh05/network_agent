# 存储边界与隔离

## 存储层

```
Application Layer
  │
  ├─ FileStore         storage/store.py      文件读写/删除
  ├─ ArtifactStore     artifacts/store.py    制品持久化 (JSONL)
  ├─ JobStore          jobs/store.py         Job 元数据 (JSON)
  ├─ SessionStore      workspace/session_store.py   Session (JSON + dir)
  ├─ RunStore          workspace/run_store.py       Run 记录 (JSON)
  ├─ ContextStore      context/store.py            JSONL 知识存储
  └─ EventStore        observability/store.py      Trace (JSON)
```

## 各 Store 职责

| Store | 数据 | 格式 | 目录 |
|-------|------|------|------|
| FileStore | 任意文件 | 原始 | `storage/` |
| ArtifactStore | 制品 (文件+元数据) | JSONL + 文件 | `workspaces/<ws>/artifacts/` |
| JobStore | Job 记录 | JSON | `workspaces/<ws>/jobs/` |
| SessionStore | Session 元数据 | JSON | `workspaces/<ws>/sessions/` |
| RunStore | 运行记录 | JSON | `workspaces/<ws>/runs/` |
| ContextStore | 知识片段 | JSONL | `workspaces/<ws>/context/` |

## 隔离规则

1. **每个 Store 有自己的存储目录**，不交叉读写。
2. **Session 删除时级联清理**：
   - Session 元数据文件
   - Session messages 目录
   - 关联的 Run 记录和 Trace 文件
   - 关联的 Job（通过 `_complete_session_job`）
3. **Artifact 不随 Session 级联删除**（独立生命周期，可作为审计记录保留）。
4. **workspace_id 为隔离边界**。不同 workspace 的数据完全隔离。

## 文件锁

- `jobs/worker.py` — 使用 `fcntl.flock` (POSIX) 或 mtime fallback (Windows)
- `storage/index.py` — 使用 `fcntl.flock` 保护索引写入
- `observability/store.py` — 使用 `fcntl.flock` 保护 trace 写入
