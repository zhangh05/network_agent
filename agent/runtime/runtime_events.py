# agent/runtime/runtime_events.py
"""RuntimeEventBus — unified event emission for turn lifecycle."""

from agent.runtime.query_engine import StreamEvent


class RuntimeEventBus:
    """Wraps state.emitter + state.audit_events + state.audit_trace into a
    single facade so callers don't need to null-check every field."""

    def __init__(self, state):
        self._emitter = state.emitter
        self._audit_events = state.audit_events
        self._audit_trace = state.audit_trace
        self._session_id = state.session.session_id
        self._turn_id = state.turn.turn_id

    # ── lifecycle events ──

    def turn_started(self, *, trace_id: str = "", user_input: str = ""):
        if self._audit_events:
            self._audit_events.emit("turn_started",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    user_input=user_input)
        self._emitter.emit(StreamEvent.RUN_STARTED, {
            "session_id": self._session_id,
            "turn_id": self._turn_id,
            "trace_id": trace_id,
        })

    def context_built(self):
        if self._audit_events:
            self._audit_events.emit("context_built",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id)

    def model_started(self, step, msg_count, tool_count):
        if self._audit_events:
            self._audit_events.emit("model_request_started",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    step=step)
        if self._audit_trace:
            self._audit_trace.record_model_request(
                self._turn_id, step, f"{msg_count} messages", tool_count)
        self._emitter.emit(StreamEvent.MODEL_STARTED, {
            "step": step, "message_count": msg_count, "tool_count": tool_count,
        })

    def model_completed(self, step, has_content, has_tool_calls, finish_reason=""):
        if self._audit_events:
            self._audit_events.emit("model_response_received",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    step=step)
        if self._audit_trace:
            self._audit_trace.record_model_response(
                self._turn_id, step,
                has_content=has_content,
                has_tool_calls=has_tool_calls,
                finish_reason=finish_reason)

    def tool_call_started(self, tool_id, step=0):
        if self._audit_events:
            self._audit_events.emit("tool_call_started",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    tool_id=tool_id)
        self._emitter.emit(StreamEvent.TOOL_CALL, {"tool_id": tool_id, "step": step})

    def tool_call_completed(self, tool_id, ok, summary):
        if self._audit_events:
            if ok:
                self._audit_events.emit("tool_call_finished",
                                        session_id=self._session_id,
                                        turn_id=self._turn_id,
                                        tool_id=tool_id, summary=summary)
            else:
                self._audit_events.emit("tool_call_failed",
                                        session_id=self._session_id,
                                        turn_id=self._turn_id,
                                        tool_id=tool_id, errors=[summary])
        self._emitter.emit(StreamEvent.TOOL_RESULT, {
            "tool_id": tool_id,
            "ok": ok,
            "summary": (summary or "")[:200],
        })

    def tool_call_failed(self, tool_id, errors):
        if self._audit_events:
            self._audit_events.emit("tool_call_failed",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    tool_id=tool_id, errors=errors)

    def approval_required(self, approval_id, tool_id):
        if self._audit_events:
            self._audit_events.emit("approval_required",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    approval_id=approval_id,
                                    tool_id=tool_id)
        self._emitter.emit(StreamEvent.APPROVAL_REQUIRED, {
            "approval_id": approval_id, "tool_id": tool_id,
        })

    def error(self, error_type, message):
        self._emitter.emit(StreamEvent.ERROR, {
            "error_type": error_type, "message": message,
        })

    def final(self, response):
        self._emitter.emit(StreamEvent.FINAL, {"final_response": response[:200]})

    def turn_completed(self):
        if self._audit_events:
            self._audit_events.emit("turn_finished",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id)

    def turn_failed(self, reason):
        if self._audit_events:
            self._audit_events.emit("turn_failed",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    reason=reason)

    def record_tool_call(self, step, tool_id, arguments_preview):
        if self._audit_trace:
            self._audit_trace.record_tool_call(
                self._turn_id, step, tool_id, arguments_preview)

    def record_tool_result(self, step, tool_id, ok, summary):
        if self._audit_trace:
            self._audit_trace.record_tool_result(
                self._turn_id, step, tool_id, ok, summary)

    def model_retry_required_tool(self, step):
        if self._audit_events:
            self._audit_events.emit("model_retry_required_tool",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    step=step)

    def catalog_expanded(self, step, added_tool_ids):
        if self._audit_events:
            self._audit_events.emit("tool_catalog_expanded",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    step=step,
                                    added_tool_ids=added_tool_ids)

    def assistant_message(self, content_len, reasoning_stripped):
        if self._audit_events:
            self._audit_events.emit("assistant_message",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    content_len=content_len,
                                    reasoning_stripped=reasoning_stripped)

    def approval_denied(self, tool_id):
        if self._audit_events:
            self._audit_events.emit("approval_denied",
                                    session_id=self._session_id,
                                    turn_id=self._turn_id,
                                    tool_id=tool_id)
