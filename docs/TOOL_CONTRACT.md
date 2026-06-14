# Tool Contract (v3.0)

## Identity

| layer | public? | example |
|---|---|---|
| canonical_tool_id | yes | `workspace.file.read` |
| handler_id | internal | `file.read` |
| capability_action | yes (planner verb) | `workspace.file.manage` |
| governance_status | yes | `active` / `disabled` / `internal` / `forbidden` |

## Rules

1. The LLM function name is generated from `canonical_tool_id`.
2. Planner candidates are filtered to `governance_status == 'active'`.
3. The API only accepts `canonical_tool_id`.
4. `handler_id` is internal-only and never appears in any public surface.
5. The public surface has no transition / retirement fields.
6. If a tool needs to be retired, its governance_status becomes
   `forbidden` and the canonical ID remains in place.

## Flow

```
user request
→ capability_action plan
→ canonical tools (preferred + fallback)
→ governance filter (active only)
→ candidate_tools
→ ToolRouter
→ handler_id dispatch
```
