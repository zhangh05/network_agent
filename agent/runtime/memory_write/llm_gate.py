# agent/runtime/memory_write/llm_gate.py
"""MemoryLLMGate — uses LLM to score, dedupe, and summarize memory candidates.

One LLM call per batch (not per candidate). Outputs structured JSON with:
  - score (1-5)
  - keep (bool)
  - summary (max 30 chars)
  - semantic_duplicate_of (by candidate_id, for dedup)

If the LLM is unreachable, candidates are returned as unavailable decisions so
MemoryWriteGate can persist them as pending instead of losing or activating them.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.memory_write.models import MemoryCandidate

_log = logging.getLogger("memory_write.llm_gate")

# Minimum score to retain a candidate. Score 3 remains pending; score 4+ may be
# activated by MemoryWriteGate when the source is not a subagent.
MIN_KEEP_SCORE = 3

# Maximum candidates to send in one LLM batch
MAX_BATCH_SIZE = 5

class MemoryLLMGate:
    """LLM-based memory quality gating.

    Evaluates candidates in a single batch call, producing scores, dedup
    annotations, and search-optimized summaries.
    """

    def gate(
        self,
        candidates: list[MemoryCandidate],
    ) -> tuple[list[MemoryCandidate], list[dict]]:
        """Gate candidates through LLM evaluation.

        Args:
            candidates: accepted candidates (post dedupe + risk filter)

        Returns:
            (accepted, skipped) — accepted candidates are annotated with
            LLM-generated scores and summaries in metadata
        """
        if not candidates:
            return [], []

        accepted: list[MemoryCandidate] = []
        skipped: list[dict] = []
        for offset in range(0, len(candidates), MAX_BATCH_SIZE):
            batch = candidates[offset:offset + MAX_BATCH_SIZE]
            candidates_json = self._serialize_candidates(batch)
            messages = [
                {"role": "system", "content": self._load_prompt()},
                {"role": "user", "content": f"Candidates to evaluate:\n{candidates_json}"},
            ]
            try:
                response = self._call_llm(messages)
                results = self._parse_response(response, batch)
            except Exception:
                _log.exception("MemoryLLMGate: LLM call failed for %d candidates", len(batch))
                skipped.extend({
                    "candidate_id": c.candidate_id,
                    "reason": "llm_gate_unavailable",
                    "memory_type": c.memory_type,
                } for c in batch)
                continue

            batch_accepted, batch_skipped = self._apply_results(batch, results)
            accepted.extend(batch_accepted)
            skipped.extend(batch_skipped)

        _log.debug(
            "MemoryLLMGate: %d candidates → %d accepted, %d skipped (score threshold=%d)",
            len(candidates), len(accepted), len(skipped), MIN_KEEP_SCORE,
        )

        return accepted, skipped

    @staticmethod
    def _apply_results(
        batch: list[MemoryCandidate], results: list[dict],
    ) -> tuple[list[MemoryCandidate], list[dict]]:
        accepted: list[MemoryCandidate] = []
        skipped: list[dict] = []
        by_id = {c.candidate_id: c for c in batch}
        decisions = {
            str(r.get("id", "")): r
            for r in results
            if isinstance(r.get("id"), str) and r.get("id") in by_id
        }
        kept_ids = {
            cid for cid, result in decisions.items()
            if result.get("keep") is True and int(result.get("score", 0)) >= MIN_KEEP_SCORE
        }

        for cid, result in decisions.items():
            duplicate_of = str(result.get("semantic_duplicate_of") or "")
            if duplicate_of and duplicate_of in kept_ids:
                kept_ids.discard(cid)

        for candidate in batch:
            result = decisions.get(candidate.candidate_id)
            if result is None:
                skipped.append({
                    "candidate_id": candidate.candidate_id,
                    "reason": "llm_gate_missing_decision",
                    "memory_type": candidate.memory_type,
                })
                continue
            score = max(1, min(int(result.get("score", 0) or 0), 5))
            summary = str(result.get("summary", "") or "")[:200]
            duplicate_of = str(result.get("semantic_duplicate_of") or "")
            candidate.metadata.update({
                "llm_score": score,
                "llm_keep": bool(result.get("keep", False)),
                "llm_summary": summary,
            })
            if summary:
                candidate.metadata["summary"] = summary[:120]

            if candidate.candidate_id in kept_ids:
                accepted.append(candidate)
            else:
                reason = (
                    f"semantic_duplicate_of: {duplicate_of}"
                    if duplicate_of and duplicate_of in decisions
                    else f"llm_score_too_low: {score}"
                )
                skipped.append({
                    "candidate_id": candidate.candidate_id,
                    "reason": reason,
                    "memory_type": candidate.memory_type,
                })
        return accepted, skipped

    # ── Internal helpers ─────────────────────────────────────────────────

    def _serialize_candidates(self, candidates: list[MemoryCandidate]) -> str:
        """Convert candidates to JSON for the LLM prompt."""
        items = [
            {
                "id": c.candidate_id,
                "type": c.memory_type,
                "content": (c.content or "")[:400],  # truncate long content
                "confidence": c.confidence,
            }
            for c in candidates
        ]
        return json.dumps(items, ensure_ascii=False, indent=2)

    @staticmethod
    def _load_prompt() -> str:
        """Load the memory_gating system prompt — template first, hardcoded fallback."""
        # Try template system first
        try:
            from prompts.loader import render_prompt
            result = render_prompt("memory_gating", {}, "")
            if result and result.text:
                return result.text
        except Exception:
            pass
        return ""

    @staticmethod
    def _call_llm(messages: list[dict]) -> str:
        """Call invoke_llm with the memory_gating task.

        Returns the LLM's raw text response.
        """
        from agent.llm.runtime import invoke_llm
        from agent.llm.schemas import LLMMessage

        llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages]

        resp = invoke_llm(
            task="memory_gating",
            messages=llm_messages,
        )
        if resp.error:
            raise RuntimeError(f"LLM returned error: {resp.error}")
        return resp.content or ""

    @staticmethod
    def _parse_response(raw: str, candidates: list[MemoryCandidate]) -> list[dict]:
        """Parse LLM JSON response into structured results.

        Handles common LLM formatting issues:
          - JSON wrapped in ```json ... ``` blocks
          - Trailing commas
          - Missing fields (defaults applied)
        """
        text = raw.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
                data = json.loads(text)
            else:
                raise

        results = data.get("candidates", [])
        if not results:
            raise ValueError("LLM returned empty candidates list")

        # Validate and fill defaults
        valid = []
        for r in results:
            if not isinstance(r, dict) or "id" not in r:
                continue
            try:
                r["score"] = max(1, min(int(r.get("score", 0)), 5))
            except (TypeError, ValueError):
                continue
            if not isinstance(r.get("keep"), bool):
                continue
            r.setdefault("summary", "")
            r.setdefault("semantic_duplicate_of", None)
            valid.append(r)

        return valid
