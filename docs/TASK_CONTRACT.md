# Task Contract

## Job ↔ Task Mapping

Each Job type dispatches to a specific Task. Tasks map to Capability IDs:

| Job Type | Capability ID | Task |
|----------|---------------|------|
| `translate_config` | `config.translate` | Single device config translation |
| `export_report` | — | Generate report artifact via `reports_engine` |
| `batch_translate_config` | `config.translate` | Iterate over multiple artifact configs |

## Task Payload Schema

```json
{
  "task_id": "task_<uuid16>",
  "job_id": "job_<uuid16>",
  "capability_id": "config.translate",
  "payload": {
    "source_config_ref": "art_<uuid16>",
    "options": {},
    "context_refs": []
  },
  "created_at": "<iso8601>"
}
```

## Task Result Schema

```json
{
  "task_id": "task_<uuid16>",
  "status": "succeeded | failed",
  "output": {
    "output_config_ref": "art_<uuid16>",
    "report_ref": "art_<uuid16>",
    "summary": "safe summary text"
  },
  "error": {
    "code": "ERROR_CODE",
    "message": "safe error message",
    "details": {}
  },
  "completed_at": "<iso8601>"
}
```

## Batch Task

```
for each source_config in artifacts:
    fresh-get job state
    run translate_config task
    append run_id to job.run_ids
    append output_artifact to job.output_artifacts
    save job state
```

## Error Handling Contract

| Rule | Description |
|------|-------------|
| All errors produce `TaskResult` with `status=failed` | Never throw uncaught |
| Error messages are redacted | No keys, paths, or config in error text |
| Timeout → cancelled state | Configurable per task type |
| Module errors → wrapped in safe error code | No raw stack traces in output |
| LLM failure → deterministic fallback | Task may still succeed degraded |
| Verification failure → task failed | `requires_verification=true` mandates pass |
