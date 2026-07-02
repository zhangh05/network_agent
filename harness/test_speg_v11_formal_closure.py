"""SPEG v11 Formal Closure — PolicyFingerprint, CanonicalDAG,
ProofTrace, ExecutionIdentity, and ProofVerifier.
"""

import hashlib
import pytest
from types import SimpleNamespace

from speg_engine.formal_closure import (
    PolicyFingerprint,
    ContextSchemaBinding,
    CanonicalDAG,
    ExecutionProofTrace,
    ExecutionIdentity,
    InvalidExecutionProofError,
    ExecutionProofVerifier,
)
from speg_engine.decision_graph import DecisionPolicySpec
from speg_engine.context_seal import ContextSeal


class TestPolicyFingerprint:
    """PolicyFingerprint is immutable and hashable."""

    def test_fingerprint_from_spec(self):
        fp = PolicyFingerprint(DecisionPolicySpec)
        assert fp.hash is not None
        assert len(fp.hash) == 16

    def test_fingerprint_deterministic(self):
        fp1 = PolicyFingerprint([("A", "X")])
        fp2 = PolicyFingerprint([("A", "X")])
        assert fp1.hash == fp2.hash

    def test_fingerprint_changes_with_spec(self):
        fp1 = PolicyFingerprint([("A", "X")])
        fp2 = PolicyFingerprint([("A", "Y")])
        assert fp1.hash != fp2.hash

    def test_size(self):
        fp = PolicyFingerprint(DecisionPolicySpec)
        assert fp.size == len(DecisionPolicySpec)


class TestContextSchemaBinding:
    """SchemaBinding ties version to context."""

    def test_binding_creation(self):
        sb = ContextSchemaBinding(schema_version=2, schema_hash="abc123")
        assert sb.schema_version == 2
        assert sb.schema_hash == "abc123"

    def test_binding_to_dict(self):
        sb = ContextSchemaBinding(2, "abc")
        d = sb.to_dict()
        assert d["schema_version"] == 2


class TestCanonicalDAG:
    """CanonicalDAG is deterministic and hashable."""

    def test_dag_sorted_deterministically(self):
        nodes = [
            {"id": "z", "tool": "exec.run", "depth": 0},
            {"id": "a", "tool": "config.manage", "depth": 0},
        ]
        dag = CanonicalDAG(nodes)
        assert dag.nodes[0]["id"] == "a"

    def test_dag_hash_deterministic(self):
        d1 = CanonicalDAG([{"id": "n1", "tool": "t1", "depth": 0}])
        d2 = CanonicalDAG([{"id": "n1", "tool": "t1", "depth": 0}])
        assert d1.hash == d2.hash

    def test_dag_hash_changes_with_nodes(self):
        d1 = CanonicalDAG([{"id": "n1", "tool": "t1", "depth": 0}])
        d2 = CanonicalDAG([{"id": "n1", "tool": "t2", "depth": 0}])
        assert d1.hash != d2.hash


class TestExecutionProofTrace:
    """ProofTrace is a verifiable cryptographic chain."""

    def test_proof_trace_chain_valid(self):
        pt = ExecutionProofTrace()
        h = "abc"
        pt.add(1, h, h, "RUN", "ok")
        pt.add(2, h, h, "RUN", "ok2")
        assert pt.verify_chain() is True

    def test_chain_broken_detected(self):
        pt = ExecutionProofTrace()
        pt.add(1, "abc", "def", "RUN", "x")
        pt.add(2, "xyz", "ghi", "RUN", "y")
        assert pt.verify_chain() is False

    def test_proof_hash_deterministic(self):
        p1 = ExecutionProofTrace()
        p1.add(1, "h", "h", "RUN")
        p2 = ExecutionProofTrace()
        p2.add(1, "h", "h", "RUN")
        assert p1.hash == p2.hash

    def test_proof_hash_changes(self):
        p1 = ExecutionProofTrace()
        p1.add(1, "h", "h", "RUN", "a")
        p2 = ExecutionProofTrace()
        p2.add(2, "h", "h", "STOP", "b")
        assert p1.hash != p2.hash


class TestExecutionIdentity:
    """ExecutionIdentity is a system-level binding."""

    def test_identity_deterministic(self):
        id1 = ExecutionIdentity("da", "ca", "pa", "tr")
        id2 = ExecutionIdentity("da", "ca", "pa", "tr")
        assert id1.hash == id2.hash

    def test_identity_changes(self):
        id1 = ExecutionIdentity("A", "B", "C", "D")
        id2 = ExecutionIdentity("A", "B", "C", "E")
        assert id1.hash != id2.hash

    def test_verify_method(self):
        id1 = ExecutionIdentity("A", "B", "C", "D")
        assert id1.verify("A", "B", "C", "D") is True
        assert id1.verify("X", "B", "C", "D") is False


class TestExecutionProofVerifier:
    """ProofVerifier validates the complete proof chain."""

    def test_full_verification(self):
        dag = CanonicalDAG([{"id": "n1", "tool": "exec.run", "depth": 0}])
        policy = PolicyFingerprint([("DEFAULT", "RUN")])
        ctx_hash = ContextSeal.seal([{"role": "user", "content": "test"}])["hash"]
        trace = ExecutionProofTrace()
        trace.add(1, ctx_hash, ctx_hash, "RUN", "output")

        result = ExecutionProofVerifier.verify(trace, dag, policy, ctx_hash)
        assert result["proof_chain_valid"] is True
        assert "identity" in result
        assert result["dag_hash"] == dag.hash


class TestFormalClosureIntegration:
    """End-to-end formal proof pipeline."""

    def test_full_pipeline(self):
        # 1. Policy
        fp = PolicyFingerprint(DecisionPolicySpec)

        # 2. Context
        sealed = ContextSeal.seal([{"role": "user", "content": "hi"}])

        # 3. DAG
        dag = CanonicalDAG([{"id": "n1", "tool": "knowledge.manage", "depth": 0}])

        # 4. Trace
        trace = ExecutionProofTrace()
        trace.add(1, sealed["hash"], sealed["hash"], "RUN", "data")

        # 5. Identity
        identity = ExecutionIdentity(dag.hash, sealed["hash"], fp.hash, trace.hash)

        # 6. Verify
        assert identity.verify(dag.hash, sealed["hash"], fp.hash, trace.hash)

        # 7. Full verifier
        result = ExecutionProofVerifier.verify(trace, dag, fp, sealed["hash"])
        assert result["proof_chain_valid"]
        assert result["identity"] == identity.hash
