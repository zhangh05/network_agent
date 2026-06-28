# Network Agent — Architecture v3.10

## Principles
1. **Single runtime** — all tool execution via ToolRuntimeClient, no direct handler bypass
2. **Single approval** — ApprovalStore is the only approval record, interrupt/resume primitives
3. **Manifest-driven** — all 21 canonical tools have runtime manifests; policy/approval/retry derive from them
4. **Durable state** — TaskState → Steps → Events → Checkpoints, recoverable at any point
5. **Auditable delivery** — trajectory + eval + audit report, every task traceable

## Architecture Documents

| Document | Phase | Content |
|----------|-------|---------|
| [Runtime Call Graph](runtime-callgraph-v3.10.md) | 1 | Full call chain: 4 entry points → 1 main path |
| Tool Manifest | 5 | 21 canonical tool manifests, policy and approval metadata |
| Workspace Boundary | 7 | Zero default fallback, cross-workspace isolation |
| Memory Governance | 8 | Write gate, pending/active/conflict, retrieval filters |
| Subagent Runtime | 9 | 7 profiles, isolated execution, tool allowlists |
| Trajectory Eval | 10 | 9 eval rules, offline scoring, feedback |
| Ecosystem Interfaces | 11 | MCP/Skill/Plugin registry, import safety |
| Delivery & GitOps | 12 | Validation gates, rollback plans, audit reports |

## Module Map

```
agent/runtime/durable/       — Durable state (Phase 2-12)
├── models.py                — TaskState, RuntimeStep, RuntimeEvent, RuntimeCheckpoint
├── store.py                 — Atomic JSON persistence, query, redaction
├── control.py               — checkpoint_task, cancel_task, retry_step, resume_task
├── interrupt.py             — interrupt_before_tool, resume_after_approval
├── subagent.py              — 7 built-in profiles, create/run/merge
├── trajectory.py            — build/evaluate/persist trajectories
└── delivery.py              — Validation gates, rollback plans, audit reports

tool_runtime/
├── manifest.py              — Runtime tool manifest dataclass
├── manifest_registry.py     — 21 canonical tool manifests, validate_all()
├── client.py                — ToolRuntimeClient with caller permission gate
├── ecosystem.py             — MCP/Skill/Plugin provider registry
├── executor.py              — ToolExecutor (all redacted=True)
└── policy.py                — ToolPolicy (parameter safety)

workspace/
├── memory_governance.py     — MemoryRecord, MemoryWriteGate, promotion
├── run_store.py             — Run record persistence
├── message_store.py         — Message persistence
└── atomic_io.py             — Atomic JSON write

agent/
├── approval.py              — ApprovalStore (single store, no legacy)
├── runtime/actions/risk.py  — RiskPolicy (manifest-driven)
├── runtime/actions/approval.py — ApprovalGate (manifest reason template)
└── runtime/actions/executor.py — ActionExecutor (interrupt injection)
```

## Key APIs

| Method | Path | Phase |
|--------|------|-------|
| GET | `/api/runtime/tasks` | 2 |
| POST | `/api/runtime/tasks/<id>/checkpoint` | 3 |
| POST | `/api/runtime/tasks/<id>/cancel` | 3 |
| POST | `/api/runtime/tasks/<id>/resume` | 3 |
| POST | `/api/runtime/tasks/<id>/steps/<sid>/retry` | 3 |
| POST | `/api/agent/approvals/<id>/resolve` | 4 |
| GET | `/api/runtime/tasks/<id>/events` | 2 |
| GET | `/api/runtime/tasks/<id>/trajectories` | 10 |
| GET | `/api/ecosystem/providers` | 11 |
| POST | `/api/runtime/tasks/<id>/audit-report` | 12 |

## Verification

```
Full harness: 1272 tests passed
Focused Phase 1-12: 92 tests passed
Frontend: 71 tests passed
```
