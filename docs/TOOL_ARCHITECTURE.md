# Tool Architecture

Network Agent v2.3 uses five layers for tools:

1. **Execution layer**: 88 stable runtime tool ids and handlers.
2. **Canonical namespace layer**: category/group/action ids for LLM and UI.
3. **Governance layer**: lifecycle status and replacement metadata.
4. **Capability action layer**: planner-level actions that expand to canonical tools.
5. **Planner/router layer**: exposes only the current turn's safe candidate tools.

The execution layer remains stable for compatibility. v2.3 does not delete
handlers. It classifies overlaps and removes redundant fragments from planner
selection while preserving historical trace interpretation.

## Identifiers

- `execution_tool_id`: bottom-layer callable id, for example `file.read`.
- `canonical_tool_id`: stable user/LLM/UI id, for example `workspace.file.read`.
- `legacy_tool_id`: old id accepted as an alias, never registered as an extra tool.
- `capability_action`: planner action, for example `network.config.analyze`.

## Planner Flow

```text
user request
→ v2.2.1 rule_scene seed
→ v2.3 capability_plan
→ tool_plan
→ governance validation
→ ToolRouter candidate whitelist
→ execution_tool_id
```

If validation fails, the planner falls back to deterministic rule-seeded
planning. The validator rejects invented tools, legacy ids in planner
candidates, invalid dependencies, unsafe host/network mixes, and non-keep
governance statuses.

## Audit

Run:

```bash
python3 scripts/audit_tool_architecture.py
python3 scripts/inspect_tool_architecture.py
```

Artifacts:

- `reports/TOOL_ARCHITECTURE_AUDIT.md`
- `reports/tool_architecture_audit.json`

