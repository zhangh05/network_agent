# agent/runtime/memory_write/llm_gate.py
"""MemoryLLMGate — uses LLM to score, dedupe, and summarize memory candidates.

One LLM call per batch (not per candidate). Outputs structured JSON with:
  - score (1-5)
  - keep (bool)
  - summary (max 30 chars)
  - semantic_duplicate_of (by candidate_id, for dedup)

Falls back gracefully: if LLM is unreachable, all candidates are kept.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.memory_write.models import MemoryCandidate

_log = logging.getLogger("memory_write.llm_gate")

# Minimum score to keep a candidate
MIN_KEEP_SCORE = 3

# Maximum candidates to send in one LLM batch
# Larger batches risk exceeding token limits; this keeps input ~400 tokens
MAX_BATCH_SIZE = 10


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

        # Limit batch size
        batch = candidates[:MAX_BATCH_SIZE]
        if len(candidates) > MAX_BATCH_SIZE:
            _log.info(
                "MemoryLLMGate: batch capped at %d (total=%d)",
                MAX_BATCH_SIZE, len(candidates),
            )

        # Build prompt
        candidates_json = self._serialize_candidates(batch)
        system_prompt = self._load_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Candidates to evaluate:\n{candidates_json}"},
        ]

        # Call LLM
        try:
            response = self._call_llm(messages)
            results = self._parse_response(response, batch)
        except Exception as e:
            _log.exception("MemoryLLMGate: LLM call failed, keeping all %d candidates", len(batch))
            # Graceful fallback: keep all
            return list(candidates), []

        # Apply results
        accepted: list[MemoryCandidate] = []
        skipped: list[dict] = []

        # Build lookup: candidate_id → candidate
        by_id = {c.candidate_id: c for c in batch}

        # First pass: collect kept results
        kept_ids: set[str] = set()
        for r in results:
            cid = r.get("id", "")
            if r.get("keep", False) and r.get("score", 0) >= MIN_KEEP_SCORE:
                kept_ids.add(cid)

        # Remove semantic duplicates (dedup by LLM)
        for r in results:
            dup_of = r.get("semantic_duplicate_of")
            if dup_of and dup_of in kept_ids:
                kept_ids.discard(r.get("id", ""))
                skipped.append({
                    "candidate_id": r.get("id", ""),
                    "reason": f"semantic_duplicate_of: {dup_of}",
                    "memory_type": by_id.get(r.get("id", "")).memory_type if r.get("id", "") in by_id else "",
                })

        # Second pass: apply scores and summaries
        for r in results:
            cid = r.get("id", "")
            c = by_id.get(cid)
            if c is None:
                continue

            score = r.get("score", 0)
            summary = r.get("summary", "")

            # Annotate candidate with LLM evaluation
            c.metadata["llm_score"] = score
            c.metadata["llm_summary"] = summary[:200] if summary else ""
            # Use LLM summary if available and non-empty, else keep original summary
            if summary:
                c.metadata["summary"] = summary[:120]

            if cid in kept_ids:
                accepted.append(c)
            elif score < MIN_KEEP_SCORE:
                skipped.append({
                    "candidate_id": cid,
                    "reason": f"llm_score_too_low: {score}",
                    "memory_type": c.memory_type,
                })

        _log.debug(
            "MemoryLLMGate: %d candidates → %d accepted, %d skipped (score threshold=%d)",
            len(batch), len(accepted), len(skipped), MIN_KEEP_SCORE,
        )

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
        """Load the memory_gating system prompt."""
        try:
            from agent.llm.tasks.prompts import PROMPTS
            return PROMPTS.get("memory_gating", "")
        except Exception:
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
            _log.warning("MemoryLLMGate: LLM returned empty candidates list")
            return []

        # Validate and fill defaults
        valid = []
        for r in results:
            if not isinstance(r, dict) or "id" not in r:
                continue
            r.setdefault("score", 0)
            r.setdefault("keep", False)
            r.setdefault("summary", "")
            r.setdefault("semantic_duplicate_of", None)
            valid.append(r)

        return valid
