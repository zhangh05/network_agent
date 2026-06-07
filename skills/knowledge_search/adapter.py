"""
Knowledge Search Skill Adapter

Routes knowledge queries to the Safe RAG knowledge retrieval pipeline.
The actual orchestration is done by the Agent composer node
(_compose_knowledge_query in agent/nodes/composer.py), which calls
load_knowledge_context from context/knowledge_loader.py.

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
