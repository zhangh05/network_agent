"""Layer constraints — re-exports from ssot_invariant."""

from core.constraints.ssot_invariant import (
    validate_all,
    graph_is_ssot, time_is_isolated,
    execution_has_no_state_access, llm_is_planning_only,
    kernel_is_dispatcher, no_direct_mutation,
    validate_layer_isolation,
)
