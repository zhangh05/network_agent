# Memory Subsystem

Network Agent memory: per-turn LLM-driven generation → BM25 retrieval.

## Pipeline Overview (5 Stages)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Generation   ssot_runtime.py → llm_memory.generate_memories()            │
│    Trigger: after every turn completes (user_input + LLM response + tools)  │
│    Output: JSON list of {content, type, confidence} items (max 3)           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Write        MemoryWriteGate → MemoryStore._save() → ContextStore.put() │
│    Gate: status/confidence thresholds, secret rejection, redaction          │
│    Side effects: disk JSON + BM25 index update                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Auto-Inject  MemoryHitsFragment → UnifiedRetriever.search_memory()       │
│    Trigger: every turn start via collect_context()                          │
│    Output: state.context["memory_hits"] → prompt auto-injection            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. Evidence     MemoryQueryPlanner → MemoryRetriever → UnifiedRetriever    │
│    Trigger: evidence_pipeline during cognition stage                        │
│    Output: MemoryItem list used in response composition                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 5. Lifecycle    confirm/reject/expire via MemoryStore API                  │
│    TTL cleanup via cleanup_expired() (dry_run → apply pattern)              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Stage 1: Generation

### Entry: `agent/runtime/ssot_runtime.py:run_ssot_turn()`

Runs **after** the turn result is computed but before return.

Two generation paths, selected by `gate_mode` (`rule_only` / `llm_first`):

### Path A — `rule_only` (default, zero cost)

Module: `agent/runtime/memory_write/rule_extract.py`

`extract_memories_rule_only(user_input, assistant_response, tool_calls)`:

- **从不调 LLM** — 纯从 tool_calls 结构化提取
- 仅匹配 `_extract_summary()` 拉取 result 中的关键字段（summary/message/output/stdout）
- 垃圾通用文本自动过滤（"ok", "success", "started"）
- 正则检测用户偏好（"用X格式"，"以后X"，"always use X"）
- Merging user_input 启发的简明键去重（prefix-80）
- 回归失败→ error_lesson
- 单 turn 硬上限 3 items（与 llm_memory 一致）

### Path B — `llm_first` (extra 0.3–0.5s)

Module: `agent/runtime/memory_write/llm_memory.py`

Single function `generate_memories(user_input, assistant_response, tool_summaries)`:

- Builds a conversation text from input + tool summaries + response
- Calls `invoke_llm(task="memory_generation", ...)` with:
  - **SYSTEM_PROMPT**: instructs the LLM to identify key facts, decisions, findings (max 3 items, 200 chars each, JSON format)
  - **USER_PROMPT**: injected conversation summary
- Parses JSON response into `[{content, type, confidence}]`
- Returns `[]` on any error (best-effort, never blocks turn)

### Memory Types

Valid values in the `type` field:
- `operational_fact` — tool results, command outputs, device settings
- `device_state` — device model, OS version, interface IPs, protocols
- `error_lesson` — failed actions, error patterns
- `user_preference` — report format, output style, language preferences
- `task_pattern` — recurring task templates

### `MemoryLLMGate` (agent/runtime/memory_write/llm_gate.py)

`MemoryLLMGate.gate(candidates)`:

- Batch LLM scoring (1-5) for memory candidates
- Generates summaries if candidate lacks usable summary
- Candidates with score < 2 are rejected (skipped with reason)
- On LLM failure: all candidates accepted with `llm_gate_unavailable_fallback` warning

Used by `MemoryWriteGate._llm_gate_record()` in `memory_governance.py` as soft gate
after write acceptance (still runs in `llm_first` mode for extra quality check).
**Note:** `generate_memories()` (llm_memory.py) already filters trivial content, so
the LLM gate in the write path is a secondary quality check. It has marginal
value when `llm_memory.py` drives generation, but remains part of the current
`llm_first` governance mode.

## Stage 2: Write

### Module: `workspace/memory_governance.py`

#### `MemoryRecord` (dataclass)

Per-memory schema. Fields:

| Field | Type | Notes |
|-------|------|-------|
| `memory_id` | str | UUID-based, auto-generated |
| `workspace_id` | str | required, validated |
| `session_id` | str | originating session |
| `scope` | str | `workspace` / `session` / `global` / `task` |
| `memory_type` | str | one of the Stage 1 types |
| `status` | str | `pending` → `active` / `rejected` / `expired` / `conflict` |
| `source` | str | `agent_suggestion` / `llm` / `user` / `manual_confirm` |
| `content` | str | actual memory text (max 2000 chars) |
| `summary` | str | searchable summary (max 200 chars) |
| `confidence` | float | 0.0–1.0, gating threshold signal |
| `redacted` | bool | True if content passed through `_redact()` |
| `metadata` | dict | `ssot_event_id`, `projection_of: "GraphStore"` |

#### `MemoryWriteGate.write(record, gate_mode)`

Sequential gate checks:

1. Workspace ID required
2. `_contains_secret_pattern()` — reject if sk-[a-zA-Z0-9]{20,}, Bearer, AKIA, etc.
3. `_is_low_value_memory()` — reject generic ("task completed successfully"), short content
4. `_redact()` — remove secrets from content + summary
5. Subagent override: always `pending`
6. `agent_suggestion` with confidence < 0.5 → `pending`
7. Confidence < 0.2 → `pending`
8. `llm_first` mode → `MemoryLLMGate.gate()` (soft quality gate)
9. `find_conflicts()` — Jaccard > 0.55 → `conflict`
10. `MemoryStore._save()`:

#### `MemoryStore._save(record)`

Two-phase write:

1. **SSOT event**: `append_memory_written()` — append-only graph event log
2. **Disk projection**: `atomic_write_json()` → `workspaces/{ws}/memory/{mem_id}.json`
3. **ContextStore index**: `ContextStore.put(item_type="memory_hit")` — BM25 index entry for retrieval

### Auto-confirm rules (confidence → status transition)

Only `user` / `manual_confirm` sources with types `operational_fact`, `artifact_summary`, `user_preference` at confidence ≥ 0.5 auto-confirm to `active`.

Other paths (LLM/agent): remain `pending` until explicit confirmation via `confirm_memory()`.

## Stage 3: Auto-Injection

### Module: `core/context/fragments/memory.py`

`MemoryHitsFragment(ContextFragment)` — runs at context collection time (per turn start).

- Calls `UnifiedRetriever.search_memory(user_input, top_k=5)`
- Renders top 3 as: `[memory_type] title\n  content` (preview 120 chars)
- Injected into state.context["memory_hits"]

### Module: `agent/runtime/prompting/safe_context_renderer.py`

Consumes `memory_hits` and renders as:

```
[memory] 2 relevant memories
[device_state] PE2: H3C MSR36-20, IPs, BGP/MPLS/ISIS
  PE2 (192.168.5.8) is H3C MSR36-20 running Comware 7.1.064...
[device_state] PE1: ...
```

### Module: `prompts/renderer.py:render_prompt()`

Handles templates with `{% for mem in memory_hits %}...{% endfor %}` loops. Renderer fills:
- `content` field (preferred, up to 400 chars)
- `summary` field (fallback)
- Title deduplication (if body starts with title, strip prefix)

## Stage 4: Evidence Pipeline

### Module: `agent/runtime/memory/retriever.py`

`MemoryRetriever.retrieve(workspace_id, MemoryQueryPlan)`:

- Wraps `UnifiedRetriever.search_memory()` → filters by `_hit_is_retrievable()` (status==active, not expired)
- Maps raw dicts to `MemoryItem` (typed dataclass)

### Module: `agent/runtime/memory/query_planner.py`

`MemoryQueryPlanner` — decides when to search memory based on query intent.

### Module: `agent/runtime/cognition/evidence_pipeline.py`

Invokes planner → retriever → merges MemoryItems into `ctx.metadata["memory_hits_count"]`.

## Stage 5: Lifecycle

### Promotion

- `confirm_memory(ws_id, memory_id)` — pending → active (for manual review)
- `reject_memory(ws_id, memory_id)` — any → rejected
- `expire_memory(ws_id, memory_id)` — any → expired

### Auto-cleanup

`MemoryStore.cleanup_expired()`:

1. Scans `items.jsonl` in ContextStore for `expires_at < now`
2. Tombstones expired entries
3. Calls `compact()` to rewrite JSONL without tombstones
4. Returns `{expired_count, compacted}`

Called during retention sweeps (`core/runtime/retention.py`).

## Storage Layout

```
workspaces/{ws}/
├── memory/
│   ├── mem-{id}.json          # MemoryRecord projection (authority for record fields)
│   └── ...
└── context/
    └── items.jsonl            # ContextStore (BM25 index entries, type="memory_hit")
```

**MemoryStore** (`workspace/memory_governance.py`) — reads projection JSON.
**ContextStore** (`core/context/context_store.py`) — reads items.jsonl for search.

## SSOT Chain

```
GraphStore event: projection.memory.written
    ↓
MemoryStore._save() → atomic_write_json()  (write-ahead: event first)
    ↓
ContextStore.put() → BM25 index update     (async best-effort, never blocks)
```

The GraphStore event is the authoritative state transition. Projections (disk JSON + BM25 index) are read-model optimizations rebuildable from the event log.

## Configuration

Workspace state (`workspace/state.json` or `workspace.yaml`):

| Key | Values | Effect |
|-----|--------|--------|
| `memory_gating` | `rule_only` (default) / `llm_first` | `llm_first` activates LLM scoring gate |

`llm_first` mode: LLM scores each candidate 1-5. Score < 2 → rejected. LLM failure → fallback to `rule_only` (all candidates kept).

## Failure Modes

| Component | Failure | Behavior |
|-----------|---------|----------|
| LLM memory generation | LLM returns error | Returns `[]`, turn continues silently |
| MemoryWriteGate | Secret pattern detected | Record rejected, status=rejected |
| ContextStore indexing | IndexError exception | Silently swallowed, memory on disk but not searchable until re-index |
| BM25 retrieval | ContextStore missing/empty | Returns empty hits, turn continues without memory context |

## Key Invariants

1. **All memory writes go through `MemoryWriteGate`** — no bypass paths.
2. **SSOT GraphStore event precedes disk write** — write-ahead log pattern.
3. **Confidence is a ranking signal, not truth** — agent/LLM suggestions stay `pending` despite high confidence; only user/authed manual confirmations auto-activate at ≥ 0.5.
4. **BM25 index is derived state** — `ContextStore.put` is best-effort; events in GraphStore can rebuild it.
