# prompts/loader.py
"""Prompt registry loader and renderer."""

from pathlib import Path
from prompts.schemas import PromptSpec, RenderedPrompt

ROOT = Path(__file__).resolve().parent

# Built-in prompt registry
_BUILTIN_PROMPTS = [
    PromptSpec(prompt_id="response.compose.v1", task="response_compose",
               template_path="prompts/templates/response_compose.md",
               description="Organize final response from agent results",
               tests=["safe_summary", "no_deployable_gen"]),
    PromptSpec(prompt_id="context.qa.v1", task="context_qa",
               template_path="prompts/templates/context_qa.md",
               description="Answer follow-up questions about last result",
               input_policy={"allow_memory": True, "allow_artifact_summary": True,
                             "allow_report_summary": True, "allow_job_summary": True,
                             "allow_trace_summary": True, "allow_knowledge_chunks": False,
                             "allow_full_source_config": False, "allow_full_deployable_config": False,
                             "allow_full_artifact_content": False, "allow_secret": False,
                             "max_context_chars": 6000}),
    PromptSpec(prompt_id="manual_review.explain.v1", task="manual_review_explain",
               template_path="prompts/templates/manual_review_explain.md",
               description="Explain manual review items"),
    PromptSpec(prompt_id="result.summarize.v1", task="result_summarize",
               template_path="prompts/templates/result_summarize.md",
               description="Summarize deterministic translation results"),
    PromptSpec(prompt_id="job_failure.explain.v1", task="job_failure_explain",
               template_path="prompts/templates/job_failure_explain.md",
               description="Explain why a job failed"),
    PromptSpec(prompt_id="report.summary.v1", task="report_summary",
               template_path="prompts/templates/report_summary.md",
               description="Summarize a report artifact"),
    PromptSpec(prompt_id="artifact_summary.explain.v1", task="artifact_summary_explain",
               template_path="prompts/templates/artifact_summary_explain.md",
               description="Explain artifact metadata"),
]

_TASK_CACHE = {p.task: p for p in _BUILTIN_PROMPTS}
_ID_CACHE = {p.prompt_id: p for p in _BUILTIN_PROMPTS}


def load_prompt_registry() -> list:
    return list(_BUILTIN_PROMPTS)


def get_prompt_by_task(task: str) -> PromptSpec:
    return _TASK_CACHE.get(task, _BUILTIN_PROMPTS[0])


def get_prompt(prompt_id: str) -> PromptSpec:
    return _ID_CACHE.get(prompt_id)


def list_prompts() -> list:
    return [p.as_dict() for p in _BUILTIN_PROMPTS]


def render_prompt(task: str, safe_context: dict = None, user_input: str = "",
                  citations: list = None, extra: dict = None) -> RenderedPrompt:
    """Render a prompt template with safe context."""
    spec = get_prompt_by_task(task)
    ctx = safe_context or {}
    citations = citations or []

    # Build safe prompt text
    lines = [
        "You are a Network Agent explanation layer.",
        "You may ONLY use the provided context below. Do NOT fabricate information.",
        "Do NOT generate, modify, or output deployable network configurations.",
        "Do NOT hide manual_review items. Do NOT claim a config is 'ready to deploy'.",
        "Do NOT output API keys, passwords, communities, tokens, or secrets.",
        "",
        "--- PROVIDED CONTEXT ---",
        f"Intent: {ctx.get('intent', '')}",
    ]

    for art in ctx.get("artifact_refs", []):
        lines.append(f"- Artifact: {art.get('artifact_id','?')} ({art.get('artifact_type','?')}): {art.get('summary','')}")

    for mem in ctx.get("memory_hits", []):
        lines.append(f"- Memory: {mem.get('title','')}: {str(mem.get('content',''))[:100]}")

    if ctx.get("last_result_summary"):
        lines.append(f"Last result: {ctx['last_result_summary']}")

    if ctx.get("job_summary"):
        js = ctx["job_summary"]
        lines.append(f"Job stats: {js}")

    for cite in citations:
        lines.append(f"- Citation [{cite.get('citation_id','?')}]: {cite.get('source_type','?')} {cite.get('source_id','?')}")

    lines.append("--- END CONTEXT ---")
    lines.append("")
    lines.append(f"User question: {user_input}")

    text = "\n".join(lines)

    return RenderedPrompt(
        prompt_id=spec.prompt_id, task=task, version=spec.version,
        text=text, context_chars=len(ctx.get("last_result_summary", "")),
        citation_ids=[c.get("citation_id", "") for c in citations],
    )


def validate_prompt_registry() -> dict:
    errors = []
    for p in _BUILTIN_PROMPTS:
        if p.output_policy.get("forbid_deployable_generation") is not True:
            errors.append(f"{p.prompt_id}: deployable generation not forbidden")
        if p.input_policy.get("allow_full_source_config") is not False:
            errors.append(f"{p.prompt_id}: allows full source_config")
        if p.input_policy.get("allow_secret") is not False:
            errors.append(f"{p.prompt_id}: allows secrets")
    return {"valid": len(errors) == 0, "errors": errors}
