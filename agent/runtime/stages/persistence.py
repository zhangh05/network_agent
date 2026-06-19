# agent/runtime/stages/persistence.py
"""PersistenceStage — persist run records and rollout."""

from agent.runtime.turn_persistence import persist_run_record


class PersistenceStage:
    """Persist turn results to storage."""

    def save_turn(self, state, result):
        # Rollout (audit service)
        try:
            if state.services and hasattr(state.services, 'audit_service') and state.services.audit_service:
                rollout = state.services.audit_service.get("rollout")
                if rollout:
                    rollout.persist_turn(state.turn, result)
        except Exception:
            pass

        persist_run_record(state.session, state.turn, result, state.context)
