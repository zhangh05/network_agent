"""
P1 fix coverage: ``prompts.loader`` must NOT silently fall back to an
unrelated prompt when the requested task is missing.

Background (5-layer audit, v3.10):

  The previous ``get_prompt_by_task(task)`` implementation returned
  ``registry[0]`` (the first registered prompt) when the task key
  did not exist. This silently substituted the wrong prompt — for
  example, a planner asking for "tool_planning" might have gotten
  the "assistant_chat" prompt, polluting the LLM context.

  The new contract:

    * ``get_prompt_by_task(task)`` raises ``PromptNotFoundError``
      (a subclass of ``KeyError``) when the task is unknown.
    * ``try_get_prompt_by_task(task)`` is the soft version: returns
      ``(spec, fallback_meta)`` where ``fallback_meta`` is a dict
      describing whether a fallback was used and why. Callers that
      need a default behavior (e.g. runtime.py) get a structured
      signal; callers that need strict behavior (e.g. context
      routes) raise.

  These tests cover both surfaces plus the ``KeyError`` backward
  compatibility (since ``PromptNotFoundError`` is a ``KeyError``
  subclass, existing ``except KeyError`` blocks still catch it).
"""

from __future__ import annotations

import pytest

from prompts.loader import (
    PromptNotFoundError,
    get_prompt_by_task,
    try_get_prompt_by_task,
)


# ── A: get_prompt_by_task raises on missing task ───────────────────────


def test_get_prompt_by_task_raises_on_missing():
    """Strict API: missing task must raise ``PromptNotFoundError``
    (a ``KeyError`` subclass), not silently return the wrong prompt.
    """
    with pytest.raises(PromptNotFoundError) as excinfo:
        get_prompt_by_task("__nonexistent_task_audit_p1__")

    # The exception carries the missing task name for diagnostics.
    assert "__nonexistent_task_audit_p1__" in str(excinfo.value)


def test_prompt_not_found_error_is_key_error_subclass():
    """Backward compat: callers that wrote ``except KeyError``
    before the v3.10 change must still catch this. Runtime.py uses
    ``except Exception`` but other call sites might use the narrower
    ``except KeyError`` form.
    """
    assert issubclass(PromptNotFoundError, KeyError)

    caught = False
    try:
        get_prompt_by_task("__another_missing__")
    except KeyError:
        caught = True
    assert caught, "PromptNotFoundError must be catchable as KeyError"


# ── B: get_prompt_by_task returns the right prompt when present ───────


def test_get_prompt_by_task_returns_correct_spec_when_present():
    """Sanity: the strict API still returns the requested spec when
    the task is in the registry. Use a well-known task key — we
    don't pin to a specific value (the registry may evolve), only
    assert that the returned spec matches what ``try_get_prompt_by_task``
    returns for the same key.
    """
    spec, _meta = try_get_prompt_by_task("assistant_chat")
    strict = get_prompt_by_task("assistant_chat")
    assert strict is spec, (
        "get_prompt_by_task and try_get_prompt_by_task must return the "
        "same object for the same task key."
    )


# ── C: try_get_prompt_by_task returns a fallback_meta dict ─────────────


def test_try_get_prompt_by_task_records_fallback_metadata():
    """Soft API: when the task is missing, returns
    ``(None_or_spec, fallback_meta)`` where ``fallback_meta`` exposes
    ``fallback=True``, ``reason`` and ``original_task``.
    """
    spec, meta = try_get_prompt_by_task("__nonexistent_task_audit_p1__")

    assert isinstance(meta, dict)
    assert meta.get("fallback") is True
    assert meta.get("original_task") == "__nonexistent_task_audit_p1__"
    assert meta.get("reason") == "task_not_found"
    # Spec may be None or the registry's first prompt — depends on
    # the chosen fallback policy. We don't pin to a specific value,
    # only assert that the meta accurately records the fallback.


def test_try_get_prompt_by_task_no_fallback_when_present():
    """Soft API: when the task IS present, the meta dict has no
    ``fallback`` flag and the returned spec matches the strict API.
    """
    spec, meta = try_get_prompt_by_task("assistant_chat")
    assert meta.get("fallback", False) is False
    # When the prompt exists, the meta may be empty (no fallback
    # info needed). We don't pin to specific keys — only assert
    # absence of fallback and identity of the returned spec.
    assert spec is get_prompt_by_task("assistant_chat")