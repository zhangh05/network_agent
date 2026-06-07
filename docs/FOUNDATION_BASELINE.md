# Foundation Baseline v0.1

## Baseline Info

| Field | Value |
|-------|-------|
| Name | Foundation Baseline v0.1 |
| Commit | `3ed03bb` |
| Date | Current |

## Scope — Included

| Component | Status |
|-----------|--------|
| Agent Runtime (LangGraph) | Complete |
| Registry (Capability/Skill/Module) | Complete |
| LLM Integration | Complete |
| Workspace Management | Complete |
| Memory | Complete |
| Observability (Trace/Logs) | Complete |
| Artifact Store | Complete |
| Report Pipeline | Complete |
| Job Runtime | Complete |
| Context Runtime | Complete |
| Prompt Runtime | Complete |
| Test Harness | Complete |
| Session Management | Complete (v3.1+) |
| config_translation (single + batch) | Complete |

## Scope — NOT Included

| Component | Status |
|-----------|--------|
| Tool Runtime | Not started |
| Knowledge Runtime | Not started |
| Topology Engine | Not started |
| Inspection Engine | Not started |
| CMDB Integration | Not started |
| Real Device Execution | Not started |

## Test Results

```
493 passed, 7 skipped, 0 failed  (Foundation Baseline)
+ 35 Session Management tests    (v3.1)
─────────────────────────────────
528 passed total
```

## Red Lines (Absolute Prohibitions)

| # | Rule |
|---|------|
| 1 | No `/api/translate` endpoint |
| 2 | No `backend/services` directory or pattern |
| 3 | No old `GraphAgent` class |
| 4 | No external `network-translator` dependency |
| 5 | No `sys.path` manipulation or `os.chdir` |
| 6 | No LLM generation of deployable config |
| 7 | No full config in Memory, Trace, or safe_llm_context |
| 8 | No key/password leak in any output layer |
| 9 | No default live API key dependency in tests |

## Next Steps (Post-Baseline)

1. ~~Session Management~~ — completed v3.1
2. Tool/Command Runtime
3. Knowledge/Index Runtime
4. Platform Hardening (auth, rate limiting, monitoring)
5. Business Modules (topology, inspection, CMDB)
