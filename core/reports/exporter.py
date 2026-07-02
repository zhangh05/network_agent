## exporter.py
"""Exporter — converts ReportDocument to file content by format."""

import json as json_lib

from core.reports.schemas import ReportDocument, ExportResult


def export_report(doc: ReportDocument, fmt: str) -> tuple:
    """Export report to (content, mime_type, file_ext). Raises ValueError on unsupported."""
    if fmt == "markdown":
        return _to_markdown(doc), "text/markdown", "md"
    elif fmt == "html":
        return _to_html(doc), "text/html", "html"
    elif fmt == "json":
        return _to_json(doc), "application/json", "json"
    elif fmt == "csv":
        return _to_csv(doc), "text/csv", "csv"
    elif fmt == "docx":
        return _skeleton("docx")
    elif fmt == "pdf":
        return _skeleton("pdf")
    else:
        raise ValueError(f"unsupported format: {fmt}")


def _to_markdown(doc: ReportDocument) -> str:
    lines = []
    for s in doc.sections:
        sec = s if isinstance(s, dict) else s.__dict__
        title = sec.get("title", "")
        level = sec.get("level", 1)
        lines.append(f"{'#' * level} {title}")
        lines.append("")
        if sec.get("content"):
            lines.append(sec["content"])
            lines.append("")
    return "\n".join(lines)


def _to_html(doc: ReportDocument) -> str:
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>",
             doc.title, "</title></head><body>"]
    for s in doc.sections:
        sec = s if isinstance(s, dict) else s.__dict__
        level = sec.get("level", 1)
        h_tag = min(level + 1, 6)
        parts.append(f"<h{h_tag}>{sec['title']}</h{h_tag}>")
        if sec.get("content"):
            ct = sec.get("content_type", "markdown")
            if ct == "code":
                parts.append(f"<pre><code>{sec['content']}</code></pre>")
            else:
                text = sec["content"].replace("\n", "<br>")
                parts.append(f"<p>{text}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _to_json(doc: ReportDocument) -> str:
    return json_lib.dumps(doc.as_dict(), indent=2, ensure_ascii=False)


def _to_csv(doc: ReportDocument) -> str:
    """CSV for table sections (manual_review, unsupported)."""
    rows = [["section_id", "title", "content_type", "sensitivity", "content"]]
    for s in doc.sections:
        sec = s if isinstance(s, dict) else s.__dict__
        rows.append([
            sec.get("section_id", ""), sec.get("title", ""),
            sec.get("content_type", ""), sec.get("sensitivity", ""),
            sec.get("content", "")[:500].replace("\n", " | "),
        ])
    return "\n".join(",".join(f'"{c}"' for c in r) for r in rows)


def _skeleton(fmt: str) -> tuple:
    """Docx/PDF skeleton — returns unsupported placeholder."""
    return (f"[{fmt.upper()} export not yet supported — skeleton placeholder]",
            f"text/plain;unsupported={fmt}", {"unsupported": fmt.upper()})
