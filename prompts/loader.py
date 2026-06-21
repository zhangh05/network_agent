# prompts/loader.py
"""Prompt registry loader and renderer — yaml-based with file templates."""

from pathlib import Path
from prompts.schemas import PromptSpec, RenderedPrompt

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "registry.yaml"
_cache = None


def _load_registry_data() -> list:
    global _cache
    if _cache is not None:
        return _cache
    try:
        import yaml
        if REGISTRY_PATH.is_file():
            data = yaml.safe_load(REGISTRY_PATH.read_text()) or {}
            prompts = []
            for entry in data.get("prompts", []):
                prompts.append(_parse_prompt(entry))
            _cache = prompts
            return prompts
    except Exception:
        pass
    # Fallback to minimal built-in
    _cache = _builtin_fallback()
    return _cache


def _parse_prompt(entry: dict) -> PromptSpec:
    inp = entry.get("input_policy", {})
    outp = entry.get("output_policy", {})
    ctx = entry.get("context_policy", {})
    return PromptSpec(
        prompt_id=entry.get("prompt_id", ""),
        task=entry.get("task", ""),
        version=entry.get("version", "v1"),
        status=entry.get("status", "enabled"),
        template_path=entry.get("template_path", ""),
        description=entry.get("description", ""),
        input_policy={
            "allow_memory": inp.get("allow_memory", True),
            "allow_artifact_summary": inp.get("allow_artifact_summary", True),
            "allow_report_summary": inp.get("allow_report_summary", True),
            "allow_job_summary": inp.get("allow_job_summary", True),
            "allow_trace_summary": inp.get("allow_trace_summary", True),
            "allow_knowledge_chunks": inp.get("allow_knowledge_chunks", False),
            "allow_full_source_config": inp.get("allow_full_source_config", False),
            "allow_full_deployable_config": inp.get("allow_full_deployable_config", False),
            "allow_full_artifact_content": inp.get("allow_full_artifact_content", False),
            "allow_secret": inp.get("allow_secret", False),
            "max_context_chars": inp.get("max_context_chars", 8000),
        },
        output_policy={
            "forbid_deployable_generation": outp.get("forbid_deployable_generation", True),
            "forbid_deployable_modification": outp.get("forbid_deployable_modification", True),
            "forbid_hide_manual_review": outp.get("forbid_hide_manual_review", True),
            "forbid_direct_deploy_claim": outp.get("forbid_direct_deploy_claim", True),
            "forbid_fake_trace_or_job_status": outp.get("forbid_fake_trace_or_job_status", True),
            "forbid_fake_artifact_id": outp.get("forbid_fake_artifact_id", True),
            "forbid_secret_output": outp.get("forbid_secret_output", True),
        },
        context_policy={
            "require_safe_llm_context": ctx.get("require_safe_llm_context", True),
            "require_citations_for_references": ctx.get("require_citations_for_references", True),
            "max_artifact_refs": ctx.get("max_artifact_refs", 10),
            "max_memory_hits": ctx.get("max_memory_hits", 5),
        },
    )


def _builtin_fallback() -> list:
    """Minimal fallback if yaml is unavailable."""
    return [
        PromptSpec(prompt_id="response.compose.v1", task="response_compose"),
        PromptSpec(prompt_id="context.qa.v1", task="context_qa"),
        PromptSpec(prompt_id="manual_review.explain.v1", task="manual_review_explain"),
        PromptSpec(prompt_id="result.summarize.v1", task="result_summarize"),
        PromptSpec(prompt_id="job_failure.explain.v1", task="job_failure_explain"),
        PromptSpec(prompt_id="report.summary.v1", task="report_summary"),
        PromptSpec(prompt_id="artifact_summary.explain.v1", task="artifact_summary_explain"),
    ]


def load_prompt_registry() -> list:
    return _load_registry_data()


def get_prompt_by_task(task: str) -> PromptSpec:
    reg = _load_registry_data()
    for p in reg:
        if p.task == task:
            return p
    return reg[0] if reg else PromptSpec(prompt_id="fallback.v1", task="response_compose")


def get_prompt(prompt_id: str) -> PromptSpec:
    for p in _load_registry_data():
        if p.prompt_id == prompt_id:
            return p
    return None


def list_prompts() -> list:
    return [p.as_dict() for p in _load_registry_data()]


def render_prompt(task: str, safe_context: dict = None, user_input: str = "",
                  citations: list = None, extra: dict = None) -> "RenderedPrompt":
    """Render a prompt template with safe context — delegates to renderer.py."""
    from prompts.renderer import render_prompt as _render
    return _render(task, safe_context=safe_context, user_input=user_input,
                   citations=citations, extra=extra)


def validate_prompt_registry() -> dict:
    errors = []
    for p in _load_registry_data():
        if p.output_policy.get("forbid_deployable_generation") is not True:
            errors.append(f"{p.prompt_id}: deployable generation not forbidden")
        if p.input_policy.get("allow_full_source_config") is not False:
            errors.append(f"{p.prompt_id}: allows full source_config")
        if p.input_policy.get("allow_secret") is not False:
            errors.append(f"{p.prompt_id}: allows secrets")
    return {"valid": len(errors) == 0, "errors": errors}
