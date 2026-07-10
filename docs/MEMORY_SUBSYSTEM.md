# Memory Subsystem

Network Agent uses one governed memory lifecycle. GraphStore is the write-ahead
source of truth; JSON records and ContextStore entries are projections.

## Runtime Flow

```text
completed turn
  -> background memory generation
  -> MemoryWriteGate
  -> GraphStore projection event
  -> workspaces/<workspace_id>/memory/<memory_id>.json
  -> active-only ContextStore projection
  -> BM25 retrieval and prompt injection
```

Memory generation runs after the user-visible response and does not block the
turn. The workspace setting `memory_gating` selects exactly one generation mode:

- `rule_only`: deterministic extraction from tool results and explicit user
  wording. It performs no extra LLM call. Agent-generated records remain
  `pending` until the user confirms them.
- `llm_first`: one LLM call extracts at most three candidates and returns
  `content`, `type`, `confidence`, `score`, `keep`, and a retrieval summary.
  That decision is attached to the candidate and reused by `MemoryWriteGate`;
  the runtime does not make a second per-memory LLM call.

Direct API or tool-created Agent candidates in `llm_first` mode use the same
batch `MemoryLLMGate`. Batches are processed in chunks of five without dropping
the remaining candidates.

## Lifecycle

Statuses:

```text
pending -> active
pending -> rejected
conflict -> active (confirmed replacement)
active -> expired
any persisted record -> physically deleted
```

Only `active` and non-expired records are retrievable. Pending, conflict,
rejected, and expired records never enter the prompt context.

Source rules:

- Explicit user/manual memory: may become `active` without LLM review.
- Rule-generated Agent memory: always `pending`.
- LLM-first Agent memory with score 4-5: `active`.
- LLM-first Agent memory with score 3: `pending`.
- LLM-first Agent memory with score 1-2 or `keep=false`: `rejected`.
- Subagent memory: always `pending`, regardless of score.
- LLM unavailable or invalid response: `pending` with
  `llm_gate_unavailable`; never accept-all and never discard silently.

Confidence is a ranking signal. It is not proof and cannot activate an Agent or
subagent claim by itself.

## Write Gate

Every production write reaches `workspace.memory_governance.MemoryWriteGate`.
The gate performs, in order:

1. Workspace, gate mode, scope, type, and required scope identifiers validation.
2. Secret detection on the original content.
3. Low-value and generic-completion rejection.
4. Redaction of persisted content and summary.
5. Source lifecycle enforcement.
6. LLM scoring in `llm_first` mode, or reuse of the turn-generation score.
7. Idempotent duplicate suppression.
8. Related-memory conflict creation.
9. GraphStore event append followed by atomic JSON projection write.
10. ContextStore projection update only when the record is retrievable.

Identical writes return the existing memory ID and status. They do not create a
second record. A conflict receives one shared `conflict_group`; confirming the
replacement expires the previous active record and updates both projections.

An LLM tool cannot overwrite an active memory in place. `memory.manage(update)`
creates a governed replacement candidate linked by `supersedes_memory_id`.

## Data Model

`MemoryRecord` contains:

- identity: `memory_id`, `workspace_id`, `session_id`, `task_id`
- lifecycle: `status`, `scope`, `source`, `created_by`
- content: `memory_type`, `content`, `summary`, `citations`
- quality: `confidence`, `metadata.llm_score`, `metadata.llm_summary`
- retention: `ttl_seconds`, `expires_at`, `last_used_at`
- conflict: `conflict_group`, `metadata.conflict_memory_ids`
- audit: `created_at`, `updated_at`, `metadata.ssot_event_id`

Supported types are `user_preference`, `task_pattern`, `tool_learning`,
`error_lesson`, `artifact_summary`, `operational_fact`, `device_state`,
`profile`, and `knowledge_note`.

Session scope requires `session_id`; task scope requires `task_id`. Conflict
detection cannot cross those boundaries.

## SSOT And Projections

Writes append `projection.memory.written` before updating the JSON projection.
Physical deletion appends `projection.memory.deleted` before removing the JSON
file. Projection failures are logged and do not change GraphStore authority.

Storage layout:

```text
workspaces/<workspace_id>/
  memory/
    mem-<id>.json
  context/
    items.jsonl
```

ContextStore uses `item_type=memory_hit`. Promotion to active creates the item;
rejection, expiration, and deletion tombstone it. `UnifiedRetriever` and
`MemoryRetriever` enforce active status again as a defense-in-depth read check.

## Retrieval

Both the REST search endpoint and `memory.manage(search)` call the shared BM25
`UnifiedRetriever`. Search applies field weighting, CJK tokenization, network
term expansion, scope boosts, recency boosts, and result deduplication.

`MemoryHitsFragment` injects at most three compact active-memory previews into
the turn context. Full recall remains available through `memory.manage(search)`.

## User Review

The Memory page lists lifecycle status and provides explicit actions for
`pending` and `conflict` records:

- Confirm and enable: promote to active; resolve a conflict by expiring the old
  active record.
- Reject: retain an audit projection but remove any retrievable projection.
- Permanent delete: append the deletion event, remove the JSON record, and
  remove the ContextStore item.

Manual creation sets `user_confirmed=true` and becomes active after safety and
conflict checks.

## Failure Semantics

| Failure | Result |
| --- | --- |
| Secret-like content | rejected before persistence of the secret |
| Generic or low-value candidate | rejected and audited |
| LLM unavailable / malformed output | pending with a fixed warning code |
| Missing LLM decision for a candidate | rejected as an invalid gate result |
| Context projection update failure | GraphStore and JSON remain authoritative; warning logged |
| Retrieval failure | no memory injected; turn continues |

## Invariants

1. No production memory write bypasses `MemoryWriteGate`.
2. GraphStore events precede projection writes.
3. Only active, non-expired records are prompt-visible.
4. User intent is not overridden by an LLM classifier.
5. Subagents cannot create active memory.
6. LLM failure cannot silently activate or discard a candidate.
7. The turn-generation score is reused; there is no per-memory double LLM call.
