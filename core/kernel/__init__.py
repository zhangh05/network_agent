"""Kernel — thin dispatcher; LLM → Kernel → Execution → EventStream."""

from core.kernel.kernel import Kernel, KernelResult, _project, _build_default_final, _run_async

__all__ = ["Kernel", "KernelResult"]