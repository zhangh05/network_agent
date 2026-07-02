"""
SSOT Runtime Engine — Single-pass Execution Graph Engine

Clean-slate Agent Runtime:
  1 request = 1 planning pass = 1 execution DAG = fully parallel runtime graph

LLM calls per request: 1 (planner) + 0-1 (optional finalizer) = max 2
No multi-turn loops, no sequential tool chains, no per-turn context rebuild.
"""

from .engine import SSOTRuntimeEngine, SSOTRuntimeConfig, SSOTRuntimeResult

__all__ = ["SSOTRuntimeEngine", "SSOTRuntimeConfig", "SSOTRuntimeResult"]
