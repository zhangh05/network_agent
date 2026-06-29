# Storage Boundaries

## Local Data Roots

| Path | Purpose | Git |
| --- | --- | --- |
| `workspaces/<workspace_id>/` | User workspace files and app data | ignored |
| `workspaces/_runtime/` | Durable task/runtime state | ignored |
| `data/` | Local JSON/JSONL runtime stores | ignored unless explicitly tracked |
| `logs/` | Local logs | ignored |
| `config/providers/` | Provider config and secrets | ignored |
| `artifacts/` | Source code for artifact store, not artifact payload data | tracked |

## Boundary Rules

- Workspace data is scoped by validated `workspace_id`.
- Store functions should not invent a workspace for caller mistakes.
- Deletion must be scoped and explicit.
- Redacted summaries may be returned in list APIs; raw secret-bearing payloads must not.

## Runtime State

Durable runtime state lives under workspace runtime storage and is addressed by task/session/workspace IDs. Task checkpoints are implementation state, not user documents.
