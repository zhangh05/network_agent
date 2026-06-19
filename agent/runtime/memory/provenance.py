# agent/runtime/memory/provenance.py
"""MemoryProvenance — stub for tracking memory item origins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProvenanceRecord:
    """Tracks where a memory item came from."""

    memory_id: str = ""
    source_turn_id: str = ""
    source_session_id: str = ""
    created_by: str = ""
    created_at: str = ""


class MemoryProvenance:
    """Track provenance of memory items. Stub for now."""

    def record(self, memory_id: str, turn_id: str = "", session_id: str = "") -> ProvenanceRecord:
        return ProvenanceRecord(
            memory_id=memory_id,
            source_turn_id=turn_id,
            source_session_id=session_id,
        )
