# Prompt Runtime

## Current Closure State

Baseline: `8cf0a1b`.

`assistant_chat` uses `safe_generate("assistant_chat")` → MiniMax-M3 LLM with deterministic fallback. It is not a business module and must not produce jobs, reports, artifacts, or `deployable_config`.

LLM output must never generate or modify `deployable_config`. Prompt input/output policy blocks full configs, secrets, fake refs, and direct device-execution claims. Negation context detection prevents false positives on safe disclaimers (e.g. "我不会声称'可直接下发'").

Frontend LLM settings are saved through `POST /api/agent/llm/config` and read through `GET /api/agent/llm/config`. The backend persists the effective UI configuration in gitignored `config/LLM_setting.json`; runtime config resolution gives this file priority over environment/file fallback. Browser localStorage must not store the API key.

## Main Chain

```
_compose_assistant_chat
  → resolve_provider_config (UI settings priority)
  → safe_generate("assistant_chat")
    → get_prompt_by_task → render_prompt (produces rendered prompt text)
    → check_prompt_input → check_prompt_text → provider(MiniMax-M3)
    → check_prompt_output → deterministic_fallback (if any step fails)
```

## Prompt Registry

- Default registry file: `prompts/registry.yaml`
- Currently registered: **8 prompts**
- Templates directory: `prompts/templates/*.md`

## Registered Prompts

| Prompt ID | Template | Purpose |
|-----------|----------|---------|
| `assistant.chat.v1` | `assistant_chat.md` | General conversation via LLM |
| `response.compose.v1` | `response_compose.md` | Main agent response composition |
| `context.qa.v1` | `context_qa.md` | Answer questions from safe context |
| `manual_review.explain.v1` | `manual_review_explain.md` | Explain manual review items |
| `result.summarize.v1` | `result_summarize.md` | Summarize run results |
| `job_failure.explain.v1` | `job_failure_explain.md` | Explain job failures |
| `report.summary.v1` | `report_summary.md` | Summarize reports |
| `artifact_summary.explain.v1` | `artifact_summary_explain.md` | Explain artifact contents |

## Negation Context Detection

`prompts/policy.py` provides `_is_negation_context(text, match_start)` — scans a window of up to 20 characters before a forbidden-pattern match for negation words:

- **CN negation**: 不, 没, 非, 不会, 不可, 绝不, 并非, 不是, 禁止, 否定
- **EN negation**: not, never, don't, doesn't, won't, can't, cannot

This prevents false positives where the LLM correctly states boundaries ("我不会声称'可直接下发'" is NOT blocked). Used in both `check_prompt_output()` and `agent/llm/policy.py::check_response()`.

## Policy History

| Date | Change |
|------|--------|
| 2026-06-07 | Removed `community\s+\S+` from FORBIDDEN_INPUT_PATTERNS (redundant with dedicated `snmp-server\s+community\s+\S+` rule; caused false positive on "community strings" in assistant_chat template) |
| 2026-06-07 | Added `_is_negation_context()` — negation-aware output policy |

## Guardrails

### check_prompt_text Failure

**BLOCKS provider execution.** No pass-through if text contains:
- Full device configs
- Secret/keys/passwords
- Deployable configuration
- Injection patterns

### check_prompt_output Failure

**Discards provider output entirely.** Falls through to deterministic fallback.
Uses negation context detection to avoid blocking safe boundary disclaimers.

## Fallback Path

Old `agent.llm.tasks.prompts` path is **NOT** the default. It is only used as fallback when:
- Prompt registry is missing or unreadable
- Requested prompt ID is not in registry

## Prompt Policy

| Rule | Description |
|------|-------------|
| No full config | Content must be summarized, not raw |
| No secret | Keys, passwords, tokens stripped |
| No deployable code | Output configs blocked |
| No "可直接下发" | Cannot claim direct deployability (negation-aware) |
| No fake refs | All artifact/run/job refs must be real |
| No hide manual_review | Must surface review items |
| Injection detection | SQL/script/command injection patterns blocked |

## Composer Task Selection

`_select_prompt_task()` routes to:

| Context | Prompt Task |
|---------|-------------|
| Assistant chat | `assistant_chat` (→ `safe_generate`) |
| User question about context | `context_qa` |
| Job failure description | `job_failure` |
| Review explanation request | `manual_review` |
| Report summary request | `report` |
| Artifact explanation request | `artifact` |
| Run result summary | `result_summarize` |
| Default / general response | `response_compose` |
