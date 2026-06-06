# jobs/runner.py
"""Job runner — executes jobs by job_type, calling run_agent/reports_engine."""

import time, sys, os, traceback

from jobs.schemas import JobRecord, JobEvent
from jobs.store import get_job, update_job, append_event, append_log
from jobs.manager import mark_running, mark_succeeded, mark_failed, update_progress


def run_job(ws_id: str, job_id: str):
    """Execute a job. Entry point called by worker/API."""
    rec = get_job(ws_id, job_id)
    if not rec:
        return

    # Planned job types: go through queued→running→succeeded
    if rec.job_type not in ("agent_run", "translate_config", "export_report", "batch_translate_config"):
        try:
            mark_running(ws_id, job_id)
        except Exception:
            pass
        mark_succeeded(ws_id, job_id, {"status": "coming_soon", "planned": True, "job_type": rec.job_type})
        return

    try:
        mark_running(ws_id, job_id)
        append_log(ws_id, job_id, f"Starting {rec.job_type} job")

        if rec.job_type == "agent_run":
            _run_agent_job(rec)
        elif rec.job_type == "translate_config":
            _run_translate_config(rec)
        elif rec.job_type == "export_report":
            _run_export_report(rec)
        elif rec.job_type == "batch_translate_config":
            _run_batch_translate(rec)

        # Fresh-get final job for accurate summary
        final = get_job(ws_id, job_id)
        mark_succeeded(ws_id, job_id, {
            "run_count": len(final.run_ids) if final else 0,
            "artifact_count": len(final.output_artifacts) if final else 0,
        })
    except Exception as e:
        error_msg = str(e)[:300]
        mark_failed(ws_id, job_id, error_msg)
        append_log(ws_id, job_id, f"Job failed: {error_msg}", level="error")


def _run_agent_job(rec: JobRecord):
    ws = rec.workspace_id
    jid = rec.job_id
    payload = dict(rec.payload)

    # Check cancel
    if _cancel_check(rec):
        return

    from agent.graph import run_agent
    result = run_agent(
        user_input=payload.pop("message", ""),
        intent=payload.pop("intent", ""),
        payload=payload,
        workspace_id=ws,
    )
    # Update job with run info
    update_job(ws, jid, {
        "run_ids": [result.get("run_id", "")],
        "trace_ids": [result.get("trace_id", "")],
        "output_artifacts": result.get("output_artifacts", []),
        "report_artifacts": result.get("report_artifacts", []),
        "result_summary": {"ok": result.get("ok")},
    })
    append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                 event_type="job_run_finished", run_id=result.get("run_id", ""),
                 message=f"Agent run completed"))


def _run_translate_config(rec: JobRecord):
    ws = rec.workspace_id
    jid = rec.job_id

    if _cancel_check(rec):
        return

    payload = dict(rec.payload)
    payload.setdefault("source_vendor", "cisco")
    payload.setdefault("target_vendor", "huawei")

    append_log(ws, jid, "Running translate_config via run_agent")
    append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                 event_type="job_run_started", message="Starting translate_config"))

    from agent.graph import run_agent
    result = run_agent(
        user_input=payload.pop("message", "translate config"),
        intent="translate_config",
        payload=payload,
        workspace_id=ws,
    )

    update_job(ws, jid, {
        "run_ids": [result.get("run_id", "")],
        "trace_ids": [result.get("trace_id", "")],
        "output_artifacts": result.get("output_artifacts", []),
        "report_artifacts": result.get("report_artifacts", []),
        "input_artifacts": result.get("input_artifacts", []),
        "artifact_refs": result.get("artifact_refs", []),
        "result_summary": {"ok": result.get("ok"), "intent": result.get("intent")},
    })
    # Record output artifact ID
    for aid in result.get("output_artifacts", []):
        append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                     event_type="job_artifact_saved", artifact_id=aid,
                     message=f"Output artifact: {aid}"))
    for aid in result.get("report_artifacts", []):
        append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                     event_type="job_report_created", artifact_id=aid,
                     message=f"Report artifact: {aid}"))


def _run_export_report(rec: JobRecord):
    ws = rec.workspace_id
    jid = rec.job_id

    if _cancel_check(rec):
        return

    payload = rec.payload
    try:
        from reports_engine.service import create_config_translation_report
        result = create_config_translation_report(
            ws, payload.get("run_id", ""), {},
            fmt=payload.get("report_format", "markdown"),
            include_deployable=payload.get("include_deployable_config", False),
        )
        if result.ok:
            update_job(ws, jid, {
                "report_artifacts": [result.artifact_id],
                "result_summary": {"report_id": result.report_id, "format": result.format},
            })
            append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                         event_type="job_report_created", artifact_id=result.artifact_id))
        else:
            mark_failed(ws, jid, result.error)
    except Exception as e:
        mark_failed(ws, jid, str(e))


def _run_batch_translate(rec: JobRecord):
    ws = rec.workspace_id
    jid = rec.job_id
    payload = rec.payload
    artifact_ids = rec.input_artifacts or payload.get("input_artifacts", [])
    fail_fast = payload.get("fail_fast", False)
    total = len(artifact_ids)
    results = []

    update_progress(ws, jid, current=0, total=total, message=f"Starting batch of {total}")

    for i, aid in enumerate(artifact_ids):
        if _cancel_check(rec):
            update_job(ws, jid, {"status": "cancelled"})
            append_event(ws, jid, JobEvent(job_id=jid, workspace_id=ws,
                         event_type="job_cancelled", message=f"Batch cancelled at {i}/{total}"))
            return

        try:
            from agent.graph import run_agent
            result = run_agent(
                user_input="translate config",
                intent="translate_config",
                payload={"artifact_id": aid, "source_vendor": "cisco", "target_vendor": "huawei"},
                workspace_id=ws,
            )
            results.append({"aid": aid, "ok": result.get("ok")})
            # Fresh-read job to avoid stale overwrite
            fresh = get_job(ws, jid)
            if not fresh: break
            # Accumulate artifacts (append, don't overwrite)
            arts = list(fresh.output_artifacts) if fresh.output_artifacts else []
            for oa in result.get("output_artifacts", []):
                if oa not in arts: arts.append(oa)
            rids = list(fresh.run_ids) if fresh.run_ids else []
            run_id = result.get("run_id", "")
            if run_id and run_id not in rids: rids.append(run_id)
            update_job(ws, jid, {"output_artifacts": arts, "run_ids": rids})
            update_progress(ws, jid, current=i+1, total=total, message=f"Translated {i+1}/{total}")
        except Exception as e:
            results.append({"aid": aid, "error": str(e)})
            if fail_fast:
                mark_failed(ws, jid, f"Batch failed at {i}/{total}: {e}")
                return

    # Fresh-get final state for summary
    final = get_job(ws, jid)
    succ = sum(1 for r in results if r.get("ok"))
    update_job(ws, jid, {"result_summary": {
        "batch_results": results, "total": total,
        "succeeded": succ, "failed": total - succ,
        "run_count": len(final.run_ids) if final else 0,
        "output_artifact_count": len(final.output_artifacts) if final else 0,
    }})


def _cancel_check(rec: JobRecord) -> bool:
    """Check if cancellation was requested. Returns True if should stop."""
    from jobs.store import get_job
    freshest = get_job(rec.workspace_id, rec.job_id)
    if freshest and freshest.cancel_requested:
        return True
    return False
