# prompts/renderer.py
"""Prompt renderer — loads templates and renders with safe context."""

from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class RenderedPrompt:
    prompt_id: str = ""
    task: str = ""
    version: str = "v1"
    text: str = ""
    context_chars: int = 0
    citation_ids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def as_dict(self): return self.__dict__.copy()


def render_prompt(task: str, safe_context: dict = None, user_input: str = "",
                  citations: list = None, extra: dict = None) -> RenderedPrompt:
    """Render a prompt by loading template and substituting safe variables."""
    from prompts.loader import get_prompt_by_task

    spec = get_prompt_by_task(task)
    ctx = safe_context or {}
    citations = citations or []

    # Load template file
    template_text = ""
    if spec.template_path:
        tp = Path(spec.template_path)
        ROOT = Path(__file__).resolve().parent.parent
        tpath = ROOT / tp if not tp.is_absolute() else tp
        if tpath.is_file():
            template_text = tpath.read_text()

    if not template_text:
        template_text = _minimal_prompt(task)

    # Substitutions
    safe_ctx_str = _safe_json(ctx)
    cite_str = _safe_json(list(citations))

    text = template_text
    text = text.replace("{{ intent }}", str(ctx.get("intent", "")))
    text = text.replace("{{ user_input }}", str(user_input))
    text = text.replace("{{ last_result_summary }}", str(ctx.get("last_result_summary", "")))
    text = text.replace("{{ job_summary }}", str(ctx.get("job_summary", "")))
    text = text.replace("{{ task }}", task)

    # Replace loops in templates
    text = _replace_template_loops(text, ctx, citations)

    return RenderedPrompt(
        prompt_id=spec.prompt_id, task=task, version=spec.version,
        text=text, context_chars=len(str(ctx)),
        citation_ids=[c.get("citation_id", "") for c in citations],
    )


def _replace_template_loops(text: str, ctx: dict, citations: list) -> str:
    """Replace simple {% for ... %} ... {% endfor %} blocks."""
    import re
    # Artifact refs
    art_block = ""
    for a in ctx.get("artifact_refs", []):
        art_block += f"- Artifact {a.get('artifact_id','?')} ({a.get('artifact_type','?')}): {a.get('summary','')}\n"
    text = re.sub(r'\{%\s*for\s+art\s+in\s+artifact_refs\s*%\}[\s\S]*?\{%\s*endfor\s*%\}', art_block, text)

    # Memory hits
    # v3.0.0+: include the full `content` field, not just the title+summary.
    # Many memory records store the actual answer in `content` (e.g. an IP
    # address, a specific port number, a hostname) while title/summary only
    # describe the topic. The previous 100-char summary cap caused the LLM
    # to see "本机 IP 地址" but never the actual IP, which made the
    # RAG-augmented answer indistinguishable from a no-context answer.
    mem_block = ""
    for m in ctx.get("memory_hits", []):
        title = (m.get("title") or "").strip()
        summary = (m.get("summary") or "").strip()
        content = (m.get("content") or "").strip()
        # Prefer content if it has substance; fall back to summary.
        body = content if len(content) > len(summary) else summary
        # Strip title prefix from body to avoid duplicating it.
        if title and body.startswith(title):
            body = body[len(title):].lstrip(" :：\n")
        line = f"- Memory: {title}"
        if body:
            line += f" — {body[:400]}"
        mem_block += line + "\n"
    text = re.sub(r'\{%\s*for\s+mem\s+in\s+memory_hits\s*%\}[\s\S]*?\{%\s*endfor\s*%\}', mem_block, text)

    # Citations
    cite_block = ""
    for c in citations:
        cite_block += f"- Citation [{c.get('citation_id','?')}]: {c.get('source_type','?')} {c.get('source_id','?')}\n"
    text = re.sub(r'\{%\s*for\s+cite\s+in\s+citations\s*%\}[\s\S]*?\{%\s*endfor\s*%\}', cite_block, text)

    return text


def _safe_json(obj) -> str:
    import json
    try:
        return json.dumps(obj, default=str)[:5000]
    except Exception:
        return str(obj)[:5000]


def _minimal_prompt(task: str) -> str:
    return f"Task: {task}\nUser: {{user_input}}\nProvide a concise, factual response based only on the context above."
