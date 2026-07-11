# agent/runtime/__init__.py
"""Runtime package exports.

Keep this module light. Eager imports here would pull in unnecessary dependencies,
creating circular imports during store/tool startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.result import AgentResult
    from agent.runtime.services import RuntimeServices, default_runtime_services
    from agent.runtime.loop import run_turn

__all__ = [
    "AgentResult",
    "RuntimeServices",
    "default_runtime_services",
    "run_turn",
]


def __getattr__(name: str):
    if name == "AgentResult":
        from agent.runtime.result import AgentResult
        return AgentResult
    if name in {"RuntimeServices", "default_runtime_services"}:
        from agent.runtime.services import RuntimeServices, default_runtime_services
        return {"RuntimeServices": RuntimeServices, "default_runtime_services": default_runtime_services}[name]
    if name == "run_turn":
        from agent.runtime.loop import run_turn
        return run_turn
    raise AttributeError(name)
