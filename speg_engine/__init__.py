"""
SPEG Engine — Single-pass Execution Graph Engine

Clean-slate Agent Runtime:
  1 request = 1 planning pass = 1 execution DAG = fully parallel runtime graph

LLM calls per request: 1 (planner) + 0-1 (optional finalizer) = max 2
No multi-turn loops, no sequential tool chains, no per-turn context rebuild.
"""

from .engine import SPEGEngine, SPEGConfig, SPEGResult

__all__ = ["SPEGEngine", "SPEGConfig", "SPEGResult"]
