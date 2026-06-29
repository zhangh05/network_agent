# Backend API Contract

## Workspace

Backend routes must validate `workspace_id` at the boundary. Empty values are invalid unless the endpoint is explicitly global health metadata.

Rules:

- Query endpoints read `workspace_id` from query string.
- Mutation endpoints read `workspace_id` from body or query as documented by the specific route.
- Do not replace missing values with `"default"` in route handlers.
- Cross-workspace lookup returns not found or invalid workspace, never leaked data.

## Tools

`/api/tools/invoke` and all agent-driven tool paths call `ToolRuntimeClient.invoke()`. Route handlers must not import or call raw handlers directly.

Tool requests require:

- `tool_id`: canonical public ID
- `arguments`: dict
- `workspace_id`: explicit workspace for workspace-scoped operations
- `requested_by`: set by server-side context

## Messages

Session messages are persisted through workspace stores. Frontend merge logic depends on stable backend message ids and roles. Do not synthesize duplicate user messages on completion events.

## Approval

Approval endpoints are workspace-scoped and backed by the single `ApprovalStore`. Resolve requests update durable runtime state through interrupt/resume logic.

## Secrets

Backend responses that may contain user content or tool output must pass through redaction before returning summary lists, histories, run lists, memory records, or trace payloads.
