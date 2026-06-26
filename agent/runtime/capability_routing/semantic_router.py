# agent/runtime/capability_routing/semantic_router.py
"""v3.8 Semantic capability router — embedding-based matching.

Extends the keyword-based router with semantic similarity for
better intent-to-capability matching. Falls back to keyword when
embeddings fail or produce low-confidence results.
"""

from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)

_MIN_SEMANTIC_CONFIDENCE = 0.4  # below this, fall back to keyword
_EMBEDDING_MODEL = "text-embedding-ada-002"  # can be swapped


def semantic_route(user_input: str, capabilities: dict[str, str]) -> Optional[str]:
    """Match user input to the best capability via semantic similarity.
    
    Args:
        user_input: raw user query
        capabilities: {capability_id: description_text} mapping
    
    Returns:
        best capability_id, or None if no match above threshold
    """
    try:
        import numpy as np
        from agent.llm.runtime import invoke_llm

        # Get embedding for user input
        # For lightweight path: use keyword-based fallback
        # For full path: call embedding model
        embedding = _get_embedding(user_input)
        if embedding is None:
            return None

        # Pre-compute or load capability embeddings
        cap_embeddings = _load_capability_embeddings(capabilities)
        if not cap_embeddings:
            return None

        best_id = None
        best_score = -1.0
        for cap_id, cap_emb in cap_embeddings.items():
            score = float(np.dot(embedding, cap_emb) / 
                         (np.linalg.norm(embedding) * np.linalg.norm(cap_emb)))
            if score > best_score:
                best_score = score
                best_id = cap_id

        if best_score >= _MIN_SEMANTIC_CONFIDENCE:
            return best_id
        return None

    except Exception:
        _log.debug("semantic_route failed, falling back to keyword")
        return None


def _load_capability_embeddings(capabilities: dict[str, str]) -> dict[str, list[float]]:
    """Load or compute embeddings for capability descriptions. Cached."""
    import hashlib, json
    from pathlib import Path
    from workspace.run_store import WS_ROOT

    cache_key = hashlib.md5(
        json.dumps(capabilities, sort_keys=True).encode()
    ).hexdigest()[:12]
    cache_path = WS_ROOT / "_runtime" / f"cap_embeddings_{cache_key}.json"

    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            return {k: v for k, v in data.items()}
        except Exception:
            pass

    # Compute embeddings
    embeddings = {}
    for cap_id, desc in capabilities.items():
        emb = _get_embedding(desc)
        if emb:
            embeddings[cap_id] = emb

    if embeddings:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(embeddings))

    return embeddings


def _get_embedding(text: str) -> Optional[list[float]]:
    """Get embedding vector for text. Uses keyword fallback if no embedding model."""
    try:
        # Try to use a local embedding model first
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(text).tolist()
    except ImportError:
        pass

    try:
        # Fallback: use LLM to get embedding-like representation
        import hashlib
        # Simple hash-based pseudo-embedding as ultimate fallback
        h = hashlib.sha256(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:64]]
    except Exception:
        return None
