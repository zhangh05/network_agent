# agent/audit/events.py
"""EventRecorder — records lifecycle events during turn execution."""

import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class AuditEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    turn_id: str = ""
    type: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventRecorder:
    def __init__(self):
        self._events: list = []

    def append(self, event: AuditEvent):
        self._events.append(event)
        return event

    def emit(self, event_type: str, session_id: str = "", turn_id: str = "", payload: dict = None, **kw):
        evt = AuditEvent(
            session_id=session_id,
            turn_id=turn_id,
            type=event_type,
            payload=payload or kw or {},
        )
        self._events.append(evt)
        return evt

    def list_events(self, turn_id: str = None, session_id: str = None) -> list:
        result = self._events
        if turn_id:
            result = [e for e in result if e.turn_id == turn_id]
        if session_id:
            result = [e for e in result if e.session_id == session_id]
        return result

    def events_for_turn(self, turn_id: str) -> list:
        return self.list_events(turn_id=turn_id)
