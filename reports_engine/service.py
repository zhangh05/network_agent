# reports_engine/service.py
"""Report service — creates reports, saves as artifacts, returns ExportResult."""

from reports_engine.schemas import ReportRequest, ReportDocument, ExportResult
from reports_engine.renderer import render_config_translation_report
from reports_engine.exporter import export_report


def create_report(request: ReportRequest, agent_result: dict = None) -> ExportResult:
    """Create a report from request."""
    try:
        if request.report_type == "config_translation":
            doc = render_config_translation_report(
                request.workspace_id, request.run_id or "",
                agent_result or {},
                request=request,
            )
        else:
            doc = ReportDocument(
                report_type=request.report_type,
                title=request.title or f"{request.report_type} report",
                format=request.format, workspace_id=request.workspace_id,
                run_id=request.run_id,
            )

        # Export
        content, mime_type, file_ext = _do_export(doc, request.format)

        # Save as artifact
        from artifacts.store import save_artifact
        artifact = save_artifact(
            workspace_id=request.workspace_id, content=content,
            artifact_type="report", title=doc.title,
            scope="run", sensitivity=doc.sensitivity,
            run_id=request.run_id, source="agent_generated",
            metadata={
                "report_id": doc.report_id, "report_type": doc.report_type,
                "format": request.format, "source_run_id": request.run_id,
                "source_artifacts": doc.source_artifacts,
                "section_count": len(doc.sections),
                "include_deployable_config": request.include_deployable_config,
                "generated_by": "reports_engine",
            },
        )

        if not artifact:
            return ExportResult(ok=False, error="artifact_save_failed")

        return ExportResult(
            ok=True, report_id=doc.report_id, artifact_id=artifact.artifact_id,
            workspace_id=request.workspace_id, run_id=request.run_id,
            format=request.format, sensitivity=doc.sensitivity,
            summary=doc.summary, size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
        )
    except Exception as e:
        return ExportResult(ok=False, error=str(e)[:200])


def create_config_translation_report(
    workspace_id: str, run_id: str, agent_result: dict,
    fmt: str = "markdown", include_deployable: bool = False,
) -> ExportResult:
    req = ReportRequest(
        workspace_id=workspace_id, run_id=run_id,
        report_type="config_translation", format=fmt,
        include_deployable_config=include_deployable,
        title="配置翻译报告",
    )
    return create_report(req, agent_result)


def _do_export(doc: ReportDocument, fmt: str) -> tuple:
    """Export and handle unsupported formats gracefully."""
    try:
        return export_report(doc, fmt)
    except ValueError:
        # Fallback to markdown for unsupported formats
        return export_report(doc, "markdown")
