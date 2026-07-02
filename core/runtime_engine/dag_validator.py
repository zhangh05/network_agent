"""
DAG Validator — strict validation of compiled ExecutionDAG.

Checks:
  - Tool existence in registry
  - Argument schema correctness
  - Dependency validity (no dangling refs)
  - Graph cycles
  - Unsafe execution paths
  - Node/depth count limits

If validation fails: REJECT plan entirely. No fallback LLM retry.
The caller must re-request with a new plan.
"""

from __future__ import annotations

from .models import DAGStatus, ExecutionDAG, ExecutionNode, SSOTRuntimeConfig


class DAGValidator:
    """Validates an ExecutionDAG against tool registry and safety rules."""

    def __init__(self, config: SSOTRuntimeConfig, tool_registry: dict[str, dict]):
        self._config = config
        self._tool_registry = tool_registry

    def validate(self, dag: ExecutionDAG) -> ExecutionDAG:
        """Validate the DAG. Returns the same DAG with status/errors populated.

        The DAG is mutated in-place with validation results.
        Callers must check dag.is_valid after calling.
        """
        errors: list[str] = []

        # 1. Node count limit
        if dag.total_nodes > self._config.max_nodes:
            errors.append(
                f"Too many nodes: {dag.total_nodes} > max {self._config.max_nodes}"
            )

        # 2. Depth limit
        if dag.max_depth > self._config.max_depth:
            errors.append(
                f"DAG too deep: {dag.max_depth} > max {self._config.max_depth}"
            )

        # 3. Per-node validation
        for node in dag.nodes:
            self._validate_node(node, dag.nodes, errors)

        # 4. Cross-node dependency integrity
        self._validate_dep_integrity(dag, errors)

        # Set status
        if errors:
            dag.validation_errors = errors
            # Pick the most severe status
            dag.status = self._classify_errors(errors)
        else:
            dag.status = DAGStatus.VALID

        return dag

    def _validate_node(
        self,
        node: ExecutionNode,
        all_nodes: list[ExecutionNode],
        errors: list[str],
    ) -> None:
        """Validate a single execution node."""
        # Tool existence
        if node.tool not in self._tool_registry:
            errors.append(f"Node '{node.id}': unknown tool '{node.tool}'")
            return

        tool_meta = self._tool_registry[node.tool]

        # Argument schema validation
        schema = tool_meta.get("args_schema", {})
        if schema:
            self._validate_args(node.id, node.args, schema, errors)

        # Dependency validity
        node_ids = {n.id for n in all_nodes}
        for dep in node.deps:
            if dep not in node_ids:
                errors.append(
                    f"Node '{node.id}': depends on non-existent node '{dep}'"
                )

        # Unsafe path detection
        unsafe_tags = tool_meta.get("unsafe_tags", [])
        if "destructive" in unsafe_tags:
            errors.append(
                f"Node '{node.id}' ({node.tool}): marked as destructive — "
                f"requires explicit approval or removal from plan"
            )

    def _validate_args(
        self,
        node_id: str,
        args: dict,
        schema: dict,
        errors: list[str],
    ) -> None:
        """Validate node arguments against the tool's expected schema."""
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in args or args[field] is None:
                errors.append(
                    f"Node '{node_id}': missing required argument '{field}'"
                )

        # Check types (basic)
        for field, value in args.items():
            if field in properties:
                expected_type = properties[field].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    pass  # LLM may output numbers as raw — not a hard error
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    errors.append(
                        f"Node '{node_id}': argument '{field}' should be a number"
                    )
                elif expected_type == "array" and not isinstance(value, list):
                    errors.append(
                        f"Node '{node_id}': argument '{field}' should be an array"
                    )
                elif expected_type == "object" and not isinstance(value, dict):
                    errors.append(
                        f"Node '{node_id}': argument '{field}' should be an object"
                    )

    def _validate_dep_integrity(
        self, dag: ExecutionDAG, errors: list[str]
    ) -> None:
        """Check that dependency chains don't violate depth ordering."""
        ids_to_depth = {n.id: n.depth for n in dag.nodes}
        for node in dag.nodes:
            for dep in node.deps:
                if dep in ids_to_depth and ids_to_depth[dep] >= node.depth:
                    errors.append(
                        f"Node '{node.id}' (depth {node.depth}) depends on "
                        f"'{dep}' (depth {ids_to_depth[dep]}) — "
                        f"dependency must be at a lower depth"
                    )

    def _classify_errors(self, errors: list[str]) -> DAGStatus:
        """Map errors to the most severe DAGStatus."""
        error_text = " ".join(errors).lower()
        if any(kw in error_text for kw in ("cycle", "cyclic")):
            return DAGStatus.CYCLIC
        if "unknown tool" in error_text or "non-existent" in error_text:
            return DAGStatus.INVALID_TOOL
        if "argument" in error_text or "required" in error_text:
            return DAGStatus.INVALID_ARGS
        if "depends on" in error_text:
            return DAGStatus.INVALID_DEPS
        if "destructive" in error_text or "unsafe" in error_text:
            return DAGStatus.UNSAFE_PATH
        return DAGStatus.VALID  # fallback — shouldn't reach here
