# Tool Governance

v2.3 classifies every canonical tool with a lifecycle status:

| Status | Meaning |
|---|---|
| `keep` | Stable capability. Planner may select it through capability actions. |
| `alias` | Compatibility-only id that resolves to a replacement. |
| `merged` | Functionally covered by a replacement; old execution remains registered. |
| `deprecated` | Direct/legacy calls remain compatible, but planner does not select it. |
| `removed_candidate` | Candidate for a future major removal after a deprecation release. |

## Current Governance Highlights

- `workspace.file.list_all` is merged into `workspace.file.list`.
- `workspace.file.path_exists` is an alias for `workspace.file.exists`.
- `web.news.search` remains callable but is deprecated from default planner use.
- `text.classify` is a removed candidate for future consolidation.
- Host execution tools remain independent and high-risk approval behavior is unchanged.

## Compatibility

Governance does not reduce the runtime registry count. Execution tools remain
88/88. Historical traces can still be read because audit metadata records:

- requested id
- canonical id
- execution id
- governance status
- replacement, when any

