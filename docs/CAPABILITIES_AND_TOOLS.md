# Capabilities and Tools (v3.0)

This document describes how capabilities and tools interact in v3.0.
For the v2.x transition history, see the deprecated v2.3 catalog at
[reports/TOOL_CATALOG_V2.3.md](../reports/TOOL_CATALOG_V2.3.md).

## Identity contract

v3.0 has only one public tool identity: `canonical_tool_id`.

| layer | public? | example |
|---|---|---|
| canonical_tool_id | yes | `workspace.file.read` |
| handler_id | internal | `file.read` |
| capability_action | yes (planner verb) | `workspace.file.manage` |
| governance_status | yes | `active` / `disabled` / `internal` / `forbidden` |

## Capability → tool flow

```
user request
→ capability_action plan
→ canonical tools (preferred + fallback)
→ governance filter (status == active)
→ candidate_tools
→ ToolRouter
→ handler_id dispatch
```

## Catalog

- Full v3.0 catalog: [docs/TOOL_CATALOG.md](TOOL_CATALOG.md)
- Machine-readable: [reports/tool_catalog.json](../reports/tool_catalog.json)

## See also

- [TOOL_ARCHITECTURE.md](TOOL_ARCHITECTURE.md)
- [TOOL_GOVERNANCE.md](TOOL_GOVERNANCE.md)
- [TOOL_CONTRACT.md](TOOL_CONTRACT.md)
