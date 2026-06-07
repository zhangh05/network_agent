# Context Runtime

## Pipeline

```
context_ref → resolver → loader → selector → compressor → builder → policy → ContextBundle
```

## ContextBundle Structure

```python
ContextBundle:
    context_id: str
    raw_items: list            # All resolved items
    selected_items: list       # After selector
    compressed_items: list     # After compressor
    execution_context: dict    # For deterministic nodes
    safe_llm_context: str      # ONLY for LLM consumption
    citations: list            # Source citations
    budget: Budget             # Token/char usage tracking
```

## Context Types

### execution_context

For deterministic nodes (skill/module/job runner):
- May contain artifact refs (IDs + summaries)
- May contain job event metadata
- **MUST NOT** contain secret plaintext, full configs, keys, or passwords

### safe_llm_context

**ONLY** for LLM consumption:
- **MUST NOT** contain: source_config, deployable_config, full report, keys, passwords, paths
- May contain: artifact summaries (max 10), job summaries, run metadata, workspace info

## Context Ref Support

| Ref Pattern | Resolves To |
|-------------|-------------|
| `last_result` | Previous run result summary |
| `last_run` | Previous run metadata |
| `last_job` | Previous job summary |
| `last_report` | Previous report summary |
| `last_artifact` | Last artifact summary |
| `artifact:<id>` | Specific artifact summary |
| `run:<id>` | Specific run metadata |
| `job:<id>` | Specific job summary |
| `report:<id>` | Specific report summary |
| `current_workspace` | Workspace metadata |
| `current_session` | Current session metadata (v3.1+) |
| `current_topology` | Topology (if available) |
| `selected_artifact` | Currently selected artifact |

## Budget

Tracks actual usage:
- `used_items`: count of items included
- `used_chars`: character count of all text
- Hard limit enforced by compressor

## Compressor Limits

| Type | Max Items |
|------|-----------|
| Memory hits | 5 |
| Artifact refs | 10 |
| Job events | 20 |
| Report sections | 10 |

## Resolution Priority

```
P0: request (user's current request)
P1: explicit_ref (user-specified context_ref)
P2: direct_result (immediate prior result)
P3: workspace (workspace-level context)
P4: memory (persisted memory hits)
P5: knowledge (knowledge base hits)
P6: historical (older run/job history)
```
