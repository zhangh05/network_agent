# Tool Governance (v3.0)

## Statuses

| status | meaning | planner visible? |
|---|---|---|
| active | planner default candidate | yes |
| disabled | not available right now | no |
| internal | runtime-only, never exposed | no |
| forbidden | refused by registry | no |

## Migration policy

To retire a tool, set its `governance_status` to `forbidden`. The
canonical_tool_id remains in place so existing references can be
audited. The catalog verifier flags any new canonical ID that is not
registered in `TOOL_NAMESPACE`.

## Code reference

```python
from tool_runtime.tool_governance import (
    TOOL_GOVERNANCE,
    governance_summary,
    planner_visible_tool_ids,
    forbid,
)

# Mark a tool as retired:
forbid("workspace.foo.bar", "removed in v3.0")
```
