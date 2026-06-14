# Tool Architecture (v3.0)

## Layers

1. **Namespace** (`tool_runtime/tool_namespace.py`): the canonical
   catalog of canonical_tool_ids and their (category, group, action,
   display_name, usage_hint, not_for, handler_id) metadata. No
   transition surface.
2. **Governance** (`tool_runtime/tool_governance.py`): per-tool
   governance_status (one of `active | disabled | internal | forbidden`).
3. **Capability actions** (`tool_runtime/capability_actions.py`):
   planner verbs that map to preferred / fallback canonical tools.
4. **Registry** (`tool_runtime/canonical_registry.py`): dispatch
   table. Public registration key is `canonical_tool_id`; private
   implementation key is `handler_id`.

## Files

| file | purpose |
|---|---|
| `tool_runtime/tool_namespace.py` | canonical catalog |
| `tool_runtime/tool_namespace_data.py` | static data |
| `tool_runtime/tool_governance.py` | status + summary |
| `tool_runtime/capability_actions.py` | planner verbs |
| `tool_runtime/canonical_registry.py` | dispatch |

## Public surface

The public surface (LLM prompt, frontend default view, docs main
tables, API catalog) exposes only:

- canonical_tool_id
- display_name
- category / group / action
- governance_status
- capability_actions
- risk_level
- requires_approval

handler_id is internal-only. It lives on the canonical registry
dataclass but is not exposed in any public payload.
