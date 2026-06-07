# context/knowledge_loader.py
"""Knowledge Loader — bridges knowledge.search into Agent safe_llm_context.

Only llm_safe chunks are loaded. No full content, config, secrets, or
absolute paths are included.
"""

from typing import List, Dict, Any
from workspace.ids import validate_workspace_id


def load_knowledge_context(
    user_input: str = "",
    workspace_id: str = "default",
    top_k: int = 5,
    artifact_type: str = None,
) -> Dict[str, Any]:
    """Search knowledge index and return safe context for Agent/LLM.

    Returns:
        {
            "results": [...],          # SearchResult safe dicts
            "count": int,              # Number of results
            "not_found": bool,         # True if no results
            "sources": [...],          # Source IDs
            "chunks": [...],           # Chunk IDs
            "query": str,              # Original query
            "top_k": int,
        }
    """
    validate_workspace_id(workspace_id)

    results = []
    not_found = True
    sources: List[str] = []
    chunks: List[str] = []

    if not user_input or not user_input.strip():
        return _empty_response(user_input, top_k)

    try:
        from knowledge.search import search
        # Extract meaningful keywords from user input for better search
        query = _extract_query(user_input)

        raw_results = search(
            workspace_id=workspace_id,
            query=query,
            artifact_type=artifact_type,
            llm_safe_only=True,
            limit=top_k,
        )

        if raw_results:
            not_found = False
            for r in raw_results:
                d = r.as_dict()
                # Security: double-check no secrets or full content
                d = _sanitize_result(d)
                results.append(d)
                if r.source_id not in sources:
                    sources.append(r.source_id)
                chunks.append(r.chunk_id)

    except Exception:
        # If search fails (e.g. index not initialized), return empty
        pass

    return {
        "results": results,
        "count": len(results),
        "not_found": not_found,
        "sources": sources,
        "chunks": chunks,
        "query": user_input,
        "top_k": top_k,
    }


def _extract_query(user_input: str) -> str:
    """Extract meaningful search keywords from user input."""
    # Remove common question patterns
    import re
    cleaned = user_input
    # Remove polite prefixes
    cleaned = re.sub(r'请问|帮我|请帮我|能不能|可不可以|能否', '', cleaned)
    # Remove knowledge context words (keep the actual search terms)
    noise_words = [
        "查一下", "找一下", "搜索", "搜一下", "检索",
        "知识库", "资料库", "资料", "文档", "文件",
        "之前上传", "上传的", "那个", "那些", "这个", "那个",
        "书里", "资料里", "文档里", "知识里", "库里",
        "根据知识", "根据资料", "根据文档",
        "有没有关于", "有没有提到", "有没有讲到",
        "提到了吗", "提到过吗", "有没有相关资料",
        "这个报告", "那个报告", "报告里", "有什么",
        "了", "吗", "呢", "？", "?", "的",
    ]
    for w in sorted(noise_words, key=len, reverse=True):
        cleaned = cleaned.replace(w, " ")
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or user_input


def _sanitize_result(d: dict) -> dict:
    """Final safety check — remove any full content or secrets."""
    blocked_keys = {
        "full_content", "full_config", "source_config", "deployable_config",
        "full_text", "full_document", "content", "text",
    }
    # Remove any blocked keys
    for k in blocked_keys:
        d.pop(k, None)

    # Check string values for secrets
    import re
    secret_re = re.compile(
        r'(password|passwd|secret|token|api_key|private_key|community|'
        r'enable\s+secret)\s*[:=]\s*\S+', re.I
    )
    for k, v in list(d.items()):
        if isinstance(v, str) and secret_re.search(v):
            d[k] = secret_re.sub("[REDACTED]", v)

    return d


def _empty_response(query: str, top_k: int) -> dict:
    return {
        "results": [], "count": 0, "not_found": True,
        "sources": [], "chunks": [], "query": query, "top_k": top_k,
    }
