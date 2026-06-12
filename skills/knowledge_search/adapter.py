"""
Knowledge Search Skill Adapter

Routes knowledge queries to the Safe RAG knowledge retrieval pipeline.
Runtime turns now use the unified retrieval layer in context/retrieval.py.
This adapter remains a direct registry/test entrypoint for the safe
knowledge context loader.

This adapter serves as the registry contract entrypoint and provides
a direct interface for testing and external callers.
"""

from context.knowledge_loader import load_knowledge_context


def search(knowledge_context: dict, query: str) -> dict:
    """Execute a knowledge search and return RAG context.

    Args:
        knowledge_context: Agent context dict containing search parameters
        query: User's knowledge search query

    Returns:
        Dict with knowledge_results, sources, and safe_llm_context
    """
    return load_knowledge_context(knowledge_context, query)
