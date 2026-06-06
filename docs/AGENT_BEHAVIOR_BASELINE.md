# Agent Behavior Baseline

## What the Agent CAN Do

| Capability | Description |
|------------|-------------|
| Config translation | Translate network device configs |
| Config review explanation | Explain review findings on translated configs |
| Manual review explanation | Explain items requiring human review |
| Artifact summary | Summarize any artifact content |
| Report summary | Summarize generated reports |
| Job summary | Summarize job execution results |
| Run summary | Summarize agent run results |
| Report export | Export reports as artifacts |
| Job translate_config | Async config translation via Job Runtime |
| Context Q&A | Answer questions based on safe context |

## What the Agent CANNOT Do

| Capability | Status |
|------------|--------|
| Topology generation | Not implemented |
| Inspection analysis | Not implemented |
| Knowledge indexing | Not implemented |
| CMDB integration | Not implemented |
| Command execution on devices | Not implemented |
| Device deployment | Not implemented |
| Auto-login to devices | Not implemented |

## What the LLM CAN Do

- Explain config translation results
- Summarize run/report/job/artifact content
- Organize and structure answers
- Explain manual_review items (what needs human attention and why)
- Answer context questions based on safe_llm_context

## What the LLM CANNOT Do

- Generate or modify deployable_config
- Hide or suppress manual_review items
- Claim a config is "可直接下发" (directly deployable)
- Fake task success (claim success when failed)
- Fake artifact/job/run/report state
- Output keys, passwords, or secrets in any form

## User Interaction Baseline

| Pattern | Behavior |
|---------|----------|
| `context_ref: last_result` | Returns previous run result summary |
| `context_ref: last_job` | Returns previous job summary |
| `context_ref: last_report` | Returns previous report summary |
| Follow-up questions | Uses safe_llm_context from prior run |
| Report requests | Report summary only (not full content) |
| Job status inquiry | Reads from JobRecord (redacted) |
| Manual review inquiry | Returns review summary from run |
| Background task request | Dispatches via Job Runtime |
