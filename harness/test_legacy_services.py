"""
Legacy services metadata tests.

- No longer tests against 8020 by default.
- Live 8020 tests gated behind RUN_LEGACY_SERVICE_TESTS=1.
- Metadata-only tests verify legacy apps exist and README documents their status.
"""

import json
import os
import sys
import urllib.request
import pytest

RUN_LIVE_LEGACY = os.environ.get("RUN_LEGACY_SERVICE_TESTS") == "1"

PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"

REQUIRES_LEGACY = pytest.mark.skipif(
    not RUN_LIVE_LEGACY,
    reason="RUN_LEGACY_SERVICE_TESTS=1 not set — 8020 is dev-only legacy",
)


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ═════════════════════════════════════════════════════════════
# Metadata Tests (always run, no network required)
# ═════════════════════════════════════════════════════════════

class TestLegacyAppsMetadata:
    """Verify legacy app directories and README documentation."""

    def test_apps_translator_service_exists(self):
        """apps/translator_service/ directory exists."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "apps", "translator_service"
        )
        assert os.path.isdir(path), "apps/translator_service/ not found"

    def test_apps_agent_service_exists(self):
        """apps/agent_service/ directory exists."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "apps", "agent_service"
        )
        assert os.path.isdir(path), "apps/agent_service/ not found"

    def test_readme_marks_legacy(self):
        """README states apps are dev-only legacy."""
        readme_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "README.md"
        )
        with open(readme_path, encoding="utf-8") as f:
            content = f.read().lower()
        assert "dev-only legacy" in content or "dev only legacy" in content, \
            "README does not mark apps as dev-only legacy"

    def test_readme_states_formal_entry(self):
        """README states formal entry point is backend/main.py on 8010."""
        readme_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "README.md"
        )
        with open(readme_path, encoding="utf-8") as f:
            content = f.read().lower()
        assert "backend/main.py" in content, \
            "README does not mention backend/main.py as entry"
        assert "8010" in content, "README does not mention port 8010"

    def test_readme_states_8020_not_formal(self):
        """README states 8020 is not formal entry."""
        readme_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "README.md"
        )
        with open(readme_path, encoding="utf-8") as f:
            content = f.read().lower()
        assert "8020" in content, "README does not mention 8020 at all"
        assert "非正式入口" in content or "not formal" in content.lower() or "dev-only legacy" in content, \
            "README does not state 8020 is not formal entry"


# ═════════════════════════════════════════════════════════════
# Live Tests (always run, hit 8010 formal entry)
# ═════════════════════════════════════════════════════════════

class TestFormalTranslate:
    """Verify /api/translate on 8010 formal entry."""

    def test_translate_returns_deployable(self):
        result = _post("/api/translate", {
            "source_config": "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n",
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["ok"] is True
        assert isinstance(result["deployable_config"], str)

    def test_translate_returns_audit_counts(self):
        result = _post("/api/translate", {
            "source_config": "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n",
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert "audit" in result
        assert "counts" in result["audit"]

    def test_translate_empty_config_returns_error(self):
        import urllib.error
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post("/api/translate", {
                "source_config": "",
                "source_vendor": "cisco",
                "target_vendor": "huawei",
            })
        assert exc.value.code == 400


# ═════════════════════════════════════════════════════════════
# Live Tests (gated — require 8020 running)
# ═════════════════════════════════════════════════════════════

@REQUIRES_LEGACY
class TestLegacyAgentLive:
    """Live tests against legacy 8020 agent_service (only when RUN_LEGACY_SERVICE_TESTS=1)."""

    LEGACY_AGENT = "http://127.0.0.1:8020"

    def _get(self, path):
        with urllib.request.urlopen(f"{self.LEGACY_AGENT}{path}", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.LEGACY_AGENT}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_agent_health(self):
        result = self._get("/health")
        assert result["ok"] is True

    def test_agent_run_translate(self):
        result = self._post("/agent/run", {
            "intent": "translate_config",
            "source_config": "interface Gi0/1\n ip addr 10.1.1.1 255.255.255.0\n",
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        })
        assert result["ok"] is True
