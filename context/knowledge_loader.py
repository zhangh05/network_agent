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
    import re
    cleaned = user_input
    # Remove polite prefixes
    cleaned = re.sub(r'请问|帮我|请帮我|能不能|可不可以|能否', '', cleaned)
    # Remove knowledge context words (keep the actual search terms)
    # Order: longer patterns first to avoid partial matches
    noise_words = [
        # Long patterns (context phrases)
        "有没有相关资料", "有没有关于",
        "提到了吗", "提到过吗", "有没有提到", "有没有讲到",
        "根据知识库回答", "根据知识库", "根据知识", "根据资料", "根据文档",
        "之前上传的文档里", "之前上传的", "上传的",
        # Location/context indicators
        "知识库里", "知识库中", "资料库里", "文档库里",
        "知识库", "资料库", "资料里", "文档里", "报告里",
        # Action verbs
        "查一下", "找一下", "搜一下", "搜索", "检索", "查找",
        # Question patterns
        "是什么", "什么是", "告诉我", "提到了", "有什么",
        # Document references
        "这个报告", "那个报告", "那个文档", "这个文档",
        "文档", "文件", "资料", "报告",
        # Demonstratives (longer first)
        "那个", "那些", "这个", "这些",
        # Punctuation
        "？", "?", "，", ",",
    ]
    for w in sorted(noise_words, key=len, reverse=True):
        cleaned = cleaned.replace(w, " ")
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Split CJK text into individual chars as additional search tokens
    # This helps match partial queries like "辣椒加肉" against "辣椒+肉"
    import unicodedata
    def _has_cjk(s):
        return any(unicodedata.category(c).startswith('Lo') or '\u4e00' <= c <= '\u9fff' for c in s)
    if _has_cjk(cleaned) and len(cleaned) > 1:
        # If the cleaned text is CJK, add space between chars for token-based search
        chars = list(cleaned)
        cleaned = ' '.join(chars)
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
