# context/__init__.py
"""Context Runtime — unified context bundle, resolver, and builder.

v3.1.0: Added unified ContextStore, UnifiedRetriever, and schema_registry.
"""

from context.schemas import (ContextBundle, ExecutionContext, SafeLLMContext,
                              ContextRef, ContextItem, ContextBudget)
from context.resolver import resolve_context_ref
from context.builder import build_context_bundle
from context.schema_registry import strip_by_schema, allowed_fields
from context.context_store import ContextStore, get_context_store
from context.unified_retriever import UnifiedRetriever, get_retriever
