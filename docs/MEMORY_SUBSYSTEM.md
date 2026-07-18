# Memory Subsystem

Network Agent uses one governed memory lifecycle and one durable store.

## Runtime Flow

```text
completed turn
  -> background memory generation
  -> MemoryWriteGate
  -> workspaces/<workspace_id>/memory/<memory_id>.json
  -> active-only ContextStore index
  -> BM25 retrieval and QueryLoop context injection
```

Memory generation runs after the visible response and does not block the turn.
The workspace setting `memory_gating` selects exactly one mode:

- `rule_only`: deterministic extraction from tool results and explicit user wording. Agent-generated records remain `pending` until confirmed.
- `llm_first`: one batched LLM call scores at most three candidates per turn. Its decision is attached to each candidate and reused by `MemoryWriteGate`; there is no second per-memory LLM call.

LLM batches are processed in chunks of five. An unavailable or malformed LLM response produces `pending` candidates with a fixed warning code; it never activates everything and never silently discards candidates.

## Lifecycle

```text
pending -> active
pending -> rejected
conflict -> active
active -> expired
persisted record -> deleted
```

Only `active`, non-expired records are retrievable. User-confirmed records may become active after safety checks. Agent and subagent suggestions cannot bypass governance; subagent records are always pending.

## Write Gate

Every production write reaches `storage.memory_governance.MemoryWriteGate`:

1. Validate workspace, gate mode, scope, type, and scope identifiers.
2. Detect secrets before redaction.
3. Reject generic completion noise and low-value content.
4. Redact persisted content, summaries, citations, and metadata.
5. Enforce source lifecycle and `llm_first` scoring.
6. Suppress identical writes idempotently.
7. Create related-memory conflicts without overwriting active records.
8. Persist the canonical JSON record atomically.
9. Update ContextStore only when the record is retrievable.

An update through `memory.manage` creates a governed replacement candidate linked by `supersedes_memory_id`; it does not mutate an active record in place.

## Data Model

`MemoryRecord` contains identity, workspace/session/task scope, lifecycle status, source, content, summary, citations, confidence, retention timestamps, conflict metadata, and redaction metadata.

Supported types are `user_preference`, `task_pattern`, `tool_learning`, `error_lesson`, `artifact_summary`, `operational_fact`, `device_state`, `profile`, and `knowledge_note`.

Session scope requires `session_id`; task scope requires `task_id`. Conflict detection never crosses those boundaries.

## Storage And Retrieval

```text
workspaces/<workspace_id>/
  memory/
    mem-<id>.json
  context/
    items.jsonl
```

Memory JSON is the canonical durable record. ContextStore is a retrievable index using `item_type=memory_hit`. Promotion creates or updates the index item; rejection, expiration, and deletion tombstone it.

REST search and `memory.manage(search)` use the shared BM25 retriever with field weighting, CJK tokenization, network-term expansion, scope and recency boosts, and result deduplication. QueryLoop receives at most three compact active-memory previews; full recall remains available through the tool.

## Invariants

1. No production memory write bypasses `MemoryWriteGate`.
2. Only active, non-expired records are prompt-visible.
3. User intent is not overridden by an LLM classifier.
4. Subagents cannot create active memory.
5. LLM failure cannot silently activate or discard a candidate.
6. The turn-generation score is reused; there is no per-memory double LLM call.
