## renderer.py
"""Report renderer — converts agent results into ReportDocuments."""

from core.reports.schemas import ReportDocument, ReportSection, ReportRequest


def render_config_translation_report(
    workspace_id: str,
    run_id: str,
    agent_result: dict,
    artifact_refs: list = None,
    request: ReportRequest = None,
) -> ReportDocument:
    """Render a config_translation report from agent result."""

    include_deployable = bool(request and request.include_deployable_config) if request else False
    fmt = request.format if request else "markdown"
    sensitivity = "sensitive" if include_deployable else "internal"

    doc = ReportDocument(
        workspace_id=workspace_id, run_id=run_id,
        report_type="config_translation",
        title=request.title if request else "配置翻译报告",
        format=fmt, sensitivity=sensitivity,
        source_artifacts=[
            a.get("artifact_id", "") for a in (artifact_refs or [])
        ],
        source_run_id=run_id,
    )

    art = artifact_refs or []
    sections = []

    # 1. Title
    sections.append(ReportSection("toc", "配置翻译报告", 1, "", "text"))

    # 2. Run info
    result = agent_result or {}
    run_info = [
        f"- Run ID: `{run_id}`",
        f"- Trace ID: `{result.get('trace_id', 'N/A')}`",
        f"- Runtime: {result.get('runtime_mode', 'fallback')}",
        f"- Capability: {result.get('result', {}).get('translator_entry', 'translate_bundle')}",
        f"- Skill: config_translation",
        f"- Module: config_translation",
    ]
    sections.append(ReportSection("run_info", "运行信息", 2, "\n".join(run_info), "markdown"))

    # 3. Input summary
    input_arts = [a for a in art if a.get("artifact_type") == "input_config"]
    inp_lines = [f"- Input artifacts: {len(input_arts)}"]
    for a in input_arts[:3]:
        m = a.get("metadata", {})
        inp_lines.append(f"  - `{a['artifact_id']}` — {a.get('title','')} ({m.get('line_count',0)} lines, vendor={m.get('probable_vendor','unknown')})")
    sections.append(ReportSection("input", "输入摘要", 2, "\n".join(inp_lines), "markdown"))

    # 4. Translation result
    res = result.get("result", {}) if isinstance(result, dict) else {}
    dc = res.get("deployable_config", "")
    mr = res.get("manual_review", [])
    sn = res.get("semantic_near", [])
    us = res.get("unsupported", [])
    qs = res.get("quality_summary", {}) if isinstance(res.get("quality_summary", {}), dict) else {}
    out_arts = [a for a in art if a.get("artifact_type") == "output_config"]
    trans_lines = [
        f"- Deployable lines: {len(dc.split(chr(10))) if dc else 0}",
        f"- Output artifacts: {len(out_arts)}",
        f"- Manual review items: {len(mr)}",
        f"- Semantic near items: {len(sn)}",
        f"- Unsupported items: {len(us)}",
        f"- Translator entry: `{res.get('translator_entry', 'translate_bundle')}`",
    ]
    for a in out_arts:
        trans_lines.append(f"- Output artifact: `{a['artifact_id']}` — {a.get('title','')}")
    sections.append(ReportSection("translation", "翻译结果摘要", 2, "\n".join(trans_lines), "markdown"))

    quality_lines = [
        f"- source_residue_count: {int(qs.get('source_residue_count', 0) or 0)}",
        f"- silent_drop_count: {int(qs.get('silent_drop_count', 0) or 0)}",
        f"- unsupported_count: {int(qs.get('unsupported_count', 0) or 0)}",
        f"- safe_drop_count: {int(qs.get('safe_drop_count', 0) or 0)}",
        f"- review_required_count: {int(qs.get('review_required_count', len(mr)) or 0)}",
    ]
    sections.append(ReportSection("quality_summary", "质量摘要", 2, "\n".join(quality_lines), "markdown"))

    # 5. Deployable config (only if requested)
    if include_deployable and dc:
        sections.append(ReportSection("deployable", "目标配置 (sensitive)", 2,
                                      f"```\n{dc}\n```", "code", "sensitive"))

    # 6. Manual review
    if mr:
        mr_lines = ["| # | Source | Reason |", "|---|--------|--------|"]
        for i, item in enumerate(mr[:20]):
            src = str(item.get("source", ""))[:40]
            reason = str(item.get("reason", ""))[:60]
            mr_lines.append(f"| {i+1} | {src} | {reason} |")
        sections.append(ReportSection("manual_review", "人工复核项", 2,
                                      "\n".join(mr_lines), "markdown", "internal"))

    # 7. Unsupported
    if us:
        us_lines = ["| # | Reason |", "|---|--------|"]
        for i, item in enumerate(us[:20]):
            reason = str(item.get("reason", ""))[:80]
            us_lines.append(f"| {i+1} | {reason} |")
        sections.append(ReportSection("unsupported", "不支持项", 2,
                                      "\n".join(us_lines), "markdown", "internal"))

    # 8. Audit
    audit = res.get("audit", {})
    if audit:
        audit_lines = [f"- {k}: {v}" for k, v in audit.items()]
        sections.append(ReportSection("audit", "审计摘要", 2, "\n".join(audit_lines), "markdown"))

    # 9. Verification
    ver = result.get("verification", {})
    if ver:
        ver_lines = [f"- {k}: {v}" for k, v in ver.items()]
        sections.append(ReportSection("verification", "验证结果", 2, "\n".join(ver_lines), "markdown"))

    # 10. Artifact references
    art_lines = [f"- Total artifacts: {len(art)}", "- Report artifact: *(this report)*"]
    for a in art:
        art_lines.append(f"  - `{a['artifact_id']}` — {a.get('artifact_type','?')} — {a.get('title','')}")
    sections.append(ReportSection("artifacts", "Artifact 引用", 2, "\n".join(art_lines), "markdown"))

    # 11. LLM participation
    llm = result.get("llm", {})
    if isinstance(llm, dict):
        llm_lines = [f"- LLM used: {llm.get('used', False)}",
                     f"- Provider: {llm.get('provider','N/A')}",
                     f"- Model: {llm.get('model','N/A')}",
                     f"- Task: {llm.get('task','N/A')}"]
        sections.append(ReportSection("llm", "AI 参与", 2, "\n".join(llm_lines), "markdown"))

    # 12. Security note
    sections.append(ReportSection("security", "安全声明", 2,
                                  "此报告已自动脱敏，不含 API key / password / community 等敏感凭证。",
                                  "markdown", "internal"))

    doc.sections = sections
    section_count = len(sections)
    doc.summary = (
        f"Config translation report with {section_count} sections, "
        f"{len(input_arts)} input, {len(out_arts)} output artifacts, "
        f"quality_summary residue={int(qs.get('source_residue_count', 0) or 0)} "
        f"silent_drop={int(qs.get('silent_drop_count', 0) or 0)} "
        f"review_required={int(qs.get('review_required_count', len(mr)) or 0)}."
    )
    doc.metadata = {
        "section_count": section_count, "report_type": "config_translation",
        "include_deployable_config": include_deployable,
        "generated_by": "core.reports",
        "quality_summary": {
            "source_residue_count": int(qs.get("source_residue_count", 0) or 0),
            "silent_drop_count": int(qs.get("silent_drop_count", 0) or 0),
            "unsupported_count": int(qs.get("unsupported_count", 0) or 0),
            "safe_drop_count": int(qs.get("safe_drop_count", 0) or 0),
            "review_required_count": int(qs.get("review_required_count", len(mr)) or 0),
        },
    }
    return doc
