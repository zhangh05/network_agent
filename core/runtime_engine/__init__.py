"""
SSOT Runtime Engine — QueryLoop production entrypoint.

The public runtime is a bounded LLM/tool loop with one canonical tool
namespace, one runtime contract set, and one audit/result surface. QueryLoop
owns planning, tool execution, retry/tracking metadata, and final response
synthesis; older DAG modules remain internal validators/test fixtures only.
"""

from .engine import SSOTRuntimeEngine, SSOTRuntimeConfig, SSOTRuntimeResult

__all__ = ["SSOTRuntimeEngine", "SSOTRuntimeConfig", "SSOTRuntimeResult"]
