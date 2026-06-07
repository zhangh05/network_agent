"""Quick smoke test for mapping_log feature."""
import sys
sys.path.insert(0, '.')

from modules.config_translation.core.rule_translator import RuleBasedTranslator
from modules.config_translation.core.translation_model import _redact_secrets_for_log


def test_mapping_log_basic():
    """Test that translate_bundle produces mapping_log with correct structure."""
    t = RuleBasedTranslator()
    config = (
        "interface GigabitEthernet0/1\n"
        " description Uplink to Core\n"
        " ip address 10.0.0.1 255.255.255.0\n"
        "!\n"
        "router bgp 65001\n"
        " bgp router-id 10.0.0.1\n"
        " neighbor 192.168.1.1 remote-as 65002\n"
    )
    result = t.translate_bundle(config, 'cisco_ios', 'huawei_vrp')
    ml = result.mapping_log

    assert len(ml) > 0, "Mapping log should not be empty"
    assert result.deployable_lines, "Should have deployable output"

    for entry in ml:
        assert "line_number" in entry
        assert "source_line" in entry
        assert "target_line" in entry
        assert "rule_id" in entry
        assert "rule_type" in entry
        assert "confidence" in entry
        assert "comment" in entry
        assert isinstance(entry["confidence"], float)
        assert 0.0 <= entry["confidence"] <= 1.0
        assert entry["rule_type"] in (
            "exact_match", "typed_ir", "passthrough", "pattern_match",
            "manual_review", "semantic_near", "unsupported", "unknown",
        )

    print(f"  mapping_log entries: {len(ml)}")
    print(f"  deployable lines: {len(result.deployable_lines)}")
    for e in ml:
        print(f"    L{e['line_number']:>2} [{e['rule_type']:<16}] conf={e['confidence']:.2f} {e['source_line'][:50]}")


def test_mapping_log_secret_redaction():
    """Test that secrets are redacted in mapping_log."""
    t = RuleBasedTranslator()
    config = "snmp-server community public RW\nenable secret 5 abc123\n"
    result = t.translate_bundle(config, 'cisco_ios', 'huawei_vrp')
    ml = result.mapping_log

    for entry in ml:
        assert "public" not in entry["source_line"].lower() or "REDACTED" in entry["source_line"], \
            f"Secret should be redacted in mapping_log: {entry['source_line']}"
        assert "abc123" not in entry["source_line"].lower() or "REDACTED" in entry["source_line"], \
            f"Secret should be redacted: {entry['source_line']}"


def test_redact_helper():
    """Test _redact_secrets_for_log standalone."""
    assert "REDACTED" in _redact_secrets_for_log("password 7 mysecret")
    assert "REDACTED" in _redact_secrets_for_log("enable secret 5 abc123")
    assert "REDACTED" in _redact_secrets_for_log("snmp-server community public RO")
    assert _redact_secrets_for_log("interface GigabitEthernet0/1") == "interface GigabitEthernet0/1"


if __name__ == "__main__":
    test_mapping_log_basic()
    test_mapping_log_secret_redaction()
    test_redact_helper()
    print("\nAll mapping_log smoke tests passed!")
