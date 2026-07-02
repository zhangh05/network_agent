"""Runtime graph package.

The canonical SSOT implementation is the append-only ``GraphStore`` event log.
Runtime state is appended as immutable events and every read model is a
projection of that log.
"""

from core.graph.event_clock import EventClock, EventStamp, get_event_clock
from core.graph.graph_store import (
    Event,
    EventType,
    GraphStore,
    assert_append_only,
    assert_event_is_immutable,
    assert_pure_reducer,
    get_graph_store,
    reduce,
    reduce_active_inspections,
    reduce_inspections,
    reset_graph_store,
)

__all__ = [
    "Event",
    "EventClock",
    "EventStamp",
    "EventType",
    "GraphStore",
    "assert_append_only",
    "assert_event_is_immutable",
    "assert_pure_reducer",
    "get_event_clock",
    "get_graph_store",
    "reduce",
    "reduce_active_inspections",
    "reduce_inspections",
    "reset_graph_store",
]
