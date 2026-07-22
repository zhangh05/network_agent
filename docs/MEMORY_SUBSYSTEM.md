# Memory Subsystem

Network Agent separates raw experience, authoritative rules, durable facts,
reusable cases, and procedures. Device state and inspection evidence remain in
their domain stores; they are never promoted into long-term memory.

## Runtime Flow

```text
completed turn
  -> append-only experience journal
  -> explicit user remember/forget command (immediate, no LLM)
  -> otherwise task boundary or four pending turns
  -> one task-level LLM reflection
  -> MemoryWriteGate safety and authority validation
  -> active-only ContextStore projection
  -> layered retrieval into QueryLoop
```

The journal is persisted before reflection, so provider failure or process
restart cannot erase the experience. Reflection processes a batch and records a
cursor only after the batch is handled.

## Memory Layers

- `core_rule`: explicit user preferences, corrections, and project policies.
- `semantic_fact`: stable identities, architecture, and verified relationships.
- `episodic_case`: reusable symptom/evidence/cause/action/result cases.
- `procedural_rule`: diagnostic and operating methods with applicability conditions.
- `knowledge_note`: manually created durable notes.
- `profile`: structured user profile data.

Raw telemetry, current device state, route or neighbor snapshots, baselines,
and artifacts remain evidence. Memory may describe how to use that evidence but
cannot replace its authority.

## Authority

Explicit user rules are active immediately after deterministic safety checks.
Agent reflection can activate semantic facts, cases, and procedures only when a
score of at least four is backed by a successful tool event. Unsupported model
inference remains pending. Subagent proposals remain pending.

Structured `memory_key` values drive replacement. A new explicit user rule with
the same key expires the previous version. Text similarity alone never declares
two memories contradictory.

## Retrieval

Active core rules in the current workspace are always injected within a small
budget. Other layers use the shared retriever. Ranking considers scope,
authority, memory layer, and relevance. Recency applies only to episodic cases;
it cannot demote an older authoritative rule or stable fact.

## Invariants

1. Every production memory write passes through `MemoryWriteGate`.
2. Only active, non-expired records are prompt-visible.
3. Assistant prose cannot create a user rule.
4. Long-term memory never becomes the authority for current network state.
5. One reflection batch makes one semantic LLM call; there is no signal or
   second gating model call.
6. Every reflected memory retains experience-event citations.
