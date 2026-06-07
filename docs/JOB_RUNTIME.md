# Job Runtime

## Current Closure State

Baseline entering completion: `ac6cadd`.

Formal job entry: `POST /api/jobs`. Job runtime exists as a task container and event/log surface. It does not imply real device execution.

Jobs must store safe summaries and refs only. Full `source_config`, full `deployable_config`, full prompts, secrets, absolute paths, and ToolResult full outputs are not job-record fields.

Planned job types return coming_soon/planned state and must not fabricate topology, inspection, CMDB, knowledge, report, or artifact results.

## Definition

Job is a **long-running task container** — NOT a new Agent instance. Jobs run asynchronously and track lifecycle, events, and logs independently from the agent run that created them.

## Lifecycle

```
created → queued → running → succeeded
                            → failed
                            → cancelled
              → paused (planned)
```

## State Transitions

### ALLOWED_TRANSITIONS

| From | To |
|------|----|
| created | queued |
| queued | running |
| queued | cancelled |
| running | succeeded |
| running | failed |
| running | cancelled |

### PLANNED_TRANSITIONS

| From | To |
|------|----|
| running | paused |
| paused | running |
| paused | cancelled |

## Job Types

### Enabled (Baseline)

| Type | Capability | Description |
|------|-----------|-------------|
| `agent_run` | — | Generic agent run container |
| `translate_config` | config.translate | Single config translation |
| `export_report` | report.export | Report generation/export |
| `batch_translate_config` | config.translate | Batch config translation |

### Planned (return `coming_soon`)

| Type | Capability |
|------|-----------|
| `topology_build` | topology.build |
| `inspection_analyze` | inspection.analyze |
| `knowledge_index` | knowledge.index |

## Runner

- Calls `run_agent()` — never directly imports Module, Skill, or LLM
- All execution goes through Agent Runtime graph

## Auto-Artifactization

On job creation, `payload.source_config` is automatically artifactized:
- Stored as `source_config_ref` with safe summary
- Full config content IS NOT placed in job record

## Redaction

`jobs/redaction.py` ensures:
- No full config in JobRecord / JobEvent / JobLog
- No keys, passwords, or paths in any job data
- Redaction at write time (before persistence)

## Batch Jobs

- Fresh-get job each step (re-read from store)
- Append `run_ids` and `output_artifacts` per step
- No overwrite of previous step results

## Worker

- Local run-once execution with file lock
- Single worker per workspace

## Workspace Integration

- Job counts tracked in workspace state: `total`, `running`, `succeeded`, `failed`
- Workspace cleanup may cancel/archive jobs

## Memory

On terminal states (succeeded/failed/cancelled), `write_job_summary()` is called to persist job summary to Memory.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs` | POST | Create job |
| `/api/jobs` | GET | List jobs |
| `/api/jobs/{id}` | GET | Get job status |
| `/api/jobs/{id}/cancel` | POST | Cancel job |
| `/api/jobs/{id}/retry` | POST | Retry failed job |
| `/api/jobs/{id}/events` | GET | Job events |
| `/api/jobs/{id}/logs` | GET | Job logs |
| `/api/jobs/{id}/artifacts` | GET | Job artifacts |
| `/api/jobs/worker/run-once` | POST | Execute one job from queue |
