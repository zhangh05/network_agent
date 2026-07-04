"""
P2a fix coverage: ``agent.runtime.prompting.safe_context_renderer`` must
produce a structurally-valid JSON payload when the safe context exceeds
the 5000-character limit.

Background (5-layer audit, v3.10):

  The previous implementation truncated the JSON string at character
  ~4900 and bolted on a fake ``"\\n}...`` tail. This produced a
  string that was neither valid JSON nor readable prose:

    * ``json.loads`` on the output raises (truncated mid-string).
    * The LLM reading it as text sees a dangling `"}...` it cannot
      parse, forcing it to either fail or invent a meaning.
    * Downstream consumers expecting JSON (debug tools, audit
      log redaction, prompt-harness snapshot tests) all break.

  The new contract: when the projected safe context exceeds 5000
  characters, replace the entire payload with a structured
  truncation marker:

    {
      "_truncated": True,
      "_original_size_chars": <int>,
      "_max_chars": 5000,
      "preview": "<first 4900 chars of the original>"
    }

  The marker itself is a complete, parseable JSON document. The
  ``preview`` field is the raw text (escaped as a JSON string
  value), not nested JSON — so reading the preview as text is
  always safe.

These tests assert the new behavior.
"""

from __future__ import annotations

import json

import pytest

from agent.runtime.prompting.safe_context_renderer import render_safe_context


# ── A: small payload still renders normally ────────────────────────────


def _projected_block(out: str) -> dict:
    """Strip the human-readable header and return the JSON projection.

    ``render_safe_context`` prepends a `[Safe Context — UNTRUSTED…]`
    header so the LLM knows the block is evidence, not instructions.
    Tests want to assert the JSON projection alone.
    """
    # The header ends with a blank line; the projection starts on the
    # next line and is the rest of the string. If the output is empty
    # (nothing projectable) we return an empty dict.
    if not out:
        return {}
    # The projection is a single JSON document; find the first '{' and
    # parse from there to the end.
    json_start = out.find("{")
    if json_start < 0:
        return {}
    return json.loads(out[json_start:])


def test_small_payload_renders_normal_json():
    """Sanity: a small safe_context that fits under 5000 chars must
    NOT be wrapped in a truncation marker."""
    safe = {
        "workspace_id": "default",
        "session_id": "audit_p2a",
        "intent": "check device",
        "last_result_summary": "device X is up",
    }
    out = render_safe_context(safe)
    assert out, "render_safe_context returned an empty string for a non-empty payload"
    parsed = _projected_block(out)
    assert "_truncated" not in parsed
    assert parsed["last_result_summary"] == "device X is up"


# ── B: large payload is replaced with a parseable truncation marker ───


def _big_payload() -> dict:
    """Build a safe_context that is large enough to trigger the
    5000-character truncation branch. Each string value is capped
    at max_text=600 by _safe_prompt_value, so we use many keys."""
    payload: dict[str, any] = {
        "artifact_refs": [{"id": f"a{i}", "summary": "X" * 600} for i in range(20)],
    }
    # Add enough scalar fields to push past 5000 chars after JSON encoding
    for i in range(20):
        payload[f"field_{i:03d}"] = "K" * 2000  # truncated to 600 by _safe_prompt_value
    return payload


def test_large_payload_truncated_to_parseable_json():
    """A safe_context that exceeds 5000 chars must produce a
    structurally-valid JSON payload — the truncation branch
    replaces the whole projection with a marker dict.
    """
    out = render_safe_context(_big_payload())
    assert out, "render_safe_context returned an empty string"
    assert "_truncated" in out, (
        "expected the truncation branch to fire for a >5000 char payload"
    )
    parsed = _projected_block(out)  # CRITICAL — must not raise

    assert parsed["_truncated"] is True
    assert parsed["_max_chars"] == 5000
    assert parsed["_original_size_chars"] > 5000
    # preview is the first 4900 chars of the original projection
    assert len(parsed["preview"]) == 4900


# ── C: truncation marker is itself a single, complete JSON document ──


def test_truncation_marker_no_orphan_quote_or_dangling_brace():
    """Regression guard: the previous behavior produced a truncated
    string with a fake `"}...` tail that broke ``json.loads`` and
    confused LLMs. The new marker is a single, complete JSON object
    that ends with ``}``.
    """
    out = render_safe_context(_big_payload())
    # The whole output (header + projection) must end with `}` —
    # no orphan quote or dangling `"}` fragment.
    assert out.rstrip().endswith("}"), (
        f"truncation marker should end with `}}`; got: {out[-60:]!r}"
    )
    parsed = _projected_block(out)
    assert "_truncated" in parsed
    assert parsed["_truncated"] is True


# ── D: truncation is stable — preview is a string (escaped) ──────────


def test_truncation_preview_is_string_not_nested_object():
    """The preview must be a JSON string (escaped), not a nested
    object — the LLM can safely read it as text and we can safely
    log it without re-parsing."""
    out = render_safe_context(_big_payload())
    parsed = _projected_block(out)

    assert isinstance(parsed["preview"], str)
    # The preview is the original projected text's first 4900
    # characters (sorted keys, JSON-dumped), so it starts with `{`.
    assert parsed["preview"].startswith("{")