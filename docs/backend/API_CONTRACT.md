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

## Inspection

`/api/inspection/*` is the HTTP surface for CMDB-driven device inspection and `inspection.manage` is the LLM-facing canonical tool.

Rules:

- All inspection endpoints require an explicit valid `workspace_id`.
- Profiles are builtin read-only command bundles; the LLM selects a profile and scope, never raw commands.
- `scope.asset_ids` is authoritative. When explicit asset ids are present, region/vendor/type/location filters must not hide those assets.
- SSH/Telnet execution must call `exec.run` with `asset_id`; credentials are resolved server-side and never returned to the frontend or LLM.
- `current_config` output is stored only as a sensitive artifact. Task JSON may include command metadata and redacted snippets, not raw configuration content.
- Mixed device outcomes use `status="partial"` instead of reporting full success.
