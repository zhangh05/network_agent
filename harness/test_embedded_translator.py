"""
Harness tests: embedded config_translation module.

Run:
    NETWORK_AGENT_PORT=8010 pytest harness/test_embedded_translator.py -v
"""

import importlib
import inspect
import json
import os
import sys
import urllib.request
import pytest


PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"

SAMPLE_CONFIG = """\
hostname Core-Router
interface GigabitEthernet0/1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 spanning-tree portfast
!
router bgp 65001
 neighbor 10.0.0.2 remote-as 65002
"""


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
        return json.loads(resp.read().decode())


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


# ── Import tests ──

def test_import_modules_config_translation_succeeds():
    """modules.config_translation.core.rule_translator imports without external repo."""
    from modules.config_translation.core.rule_translator import RuleBasedTranslator
    assert RuleBasedTranslator is not None


def test_import_translation_model_succeeds():
    """modules.config_translation.core.translation_model imports."""
    import modules.config_translation.core.translation_model as tm
    assert hasattr(tm, "TranslationBundle")
    assert hasattr(tm, "TranslationCandidate")


def test_import_deployable_policy_succeeds():
    """modules.config_translation.core.deployable_policy imports."""
    import modules.config_translation.core.deployable_policy as dp
    assert hasattr(dp, "DeployablePolicy")


def test_import_ir_parser_succeeds():
    """modules.config_translation.core.ir_parser imports."""
    import modules.config_translation.core.ir_parser as ip
    assert hasattr(ip, "parse_typed_ir")


def test_import_typed_renderer_succeeds():
    """modules.config_translation.core.typed_renderer imports."""
    import modules.config_translation.core.typed_renderer as tr
    assert hasattr(tr, "render_typed_ir")


def test_import_parser_config_block_parser_succeeds():
    """modules.config_translation.core.parser.config_block_parser imports."""
    import modules.config_translation.core.parser.config_block_parser as cbp
    assert hasattr(cbp, "parse_config_blocks")


def test_import_typed_ir_succeeds():
    """modules.config_translation.core.typed_ir imports."""
    import modules.config_translation.core.typed_ir as tdi
    assert hasattr(tdi, "TypedIRBundle")


def test_import_translation_candidate_factory_succeeds():
    """modules.config_translation.core.translation_candidate_factory imports."""
    import modules.config_translation.core.translation_candidate_factory as tcf
    assert hasattr(tcf, "try_make_candidate")


# ── No external dependency tests ──

def test_no_external_translator_path_in_sys_path():
    """sys.path does NOT contain any path with 'network-translator'."""
    for p in sys.path:
        assert "network-translator" not in str(p), f"External path found: {p}"


def test_no_external_codex_net_trans_in_sys_modules():
    """sys.modules does not reference external codex_net_trans path."""
    for name, mod in list(sys.modules.items()):
        if mod is not None and hasattr(mod, "__file__") and mod.__file__ is not None:
            assert "codex_net_trans" not in mod.__file__, \
                f"Module {name} references external codex_net_trans: {mod.__file__}"


def test_service_has_no_os_chdir():
    """backend/services/config_translation/service.py does not call os.chdir."""
    import backend.services.config_translation.service as svc
    import dis
    source = inspect.getsource(svc)
    # Strip docstring, only check code after it
    lines = source.split("\n")
    code_lines = []
    in_doc = False
    doc_done = False
    for line in lines:
        stripped = line.strip()
        if not doc_done and (stripped.startswith('"""') or stripped.startswith("'''")):
            if in_doc:
                in_doc = False
                doc_done = True
            else:
                in_doc = True
            continue
        if in_doc:
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert "os.chdir" not in code, "os.chdir call found in config_translation service code"


def test_service_has_no_sys_path_insert():
    """backend/services/config_translation/service.py does not call sys.path.insert."""
    import backend.services.config_translation.service as svc
    source = inspect.getsource(svc)
    # Strip docstring, only check code after it
    lines = source.split("\n")
    code_lines = []
    in_doc = False
    doc_done = False
    for line in lines:
        stripped = line.strip()
        if not doc_done and (stripped.startswith('"""') or stripped.startswith("'''")):
            if in_doc:
                in_doc = False
                doc_done = True
            else:
                in_doc = True
            continue
        if in_doc:
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert "sys.path" not in code, "sys.path found in config_translation service code"


def test_settings_has_no_translator_project_path():
    """backend/core/settings.py has no TRANSLATOR_PROJECT_PATH."""
    import backend.core.settings as stg
    assert not hasattr(stg, "TRANSLATOR_PROJECT_PATH"), \
        "TRANSLATOR_PROJECT_PATH still present in settings"


# ── Version API tests ──

def test_version_reports_embedded():
    """GET /api/version reports config_translation_source=embedded."""
    data = _get("/api/version")
    assert data["config_translation_source"] == "embedded"


def test_version_reports_no_external_dep():
    """GET /api/version reports external_translator_dependency=false."""
    data = _get("/api/version")
    assert data["external_translator_dependency"] is False


# ── Translate API tests ──

def test_api_translate_works_with_embedded():
    """POST /api/translate works with embedded module, no external repo needed."""
    data = _post("/api/translate", {
        "source_config": SAMPLE_CONFIG,
        "source_vendor": "auto",
        "target_vendor": "huawei",
    })
    assert "deployable_config" in data
    assert "manual_review" in data
    assert "audit" in data
    assert "elapsed_ms" in data
    # Core field: at least some output
    assert isinstance(data["deployable_config"], str)


def test_api_translate_empty_config():
    """POST /api/translate with empty config returns 400 (required field)."""
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post("/api/translate", {
            "source_config": "",
            "source_vendor": "auto",
            "target_vendor": "huawei",
        })
    assert exc.value.code == 400


def test_api_translate_cisco_to_huawei_interface():
    """Cisco interface → Huawei interface produces deployable output."""
    data = _post("/api/translate", {
        "source_config": (
            "interface GigabitEthernet0/0/1\n"
            " ip address 10.1.1.1 255.255.255.0\n"
            " no shutdown\n"
        ),
        "source_vendor": "cisco",
        "target_vendor": "huawei",
    })
    assert data["deployable_config"] is not None
    assert "elapsed_ms" in data


def test_rule_based_translator_instance_works():
    """RuleBasedTranslator instances can call translate_bundle."""
    from modules.config_translation.core.rule_translator import RuleBasedTranslator
    t = RuleBasedTranslator()
    bundle = t.translate_bundle(
        "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n",
        "cisco",
        "huawei",
    )
    assert bundle is not None
    assert hasattr(bundle, "deployable_lines")
    assert hasattr(bundle, "manual_review_items")


# ── No legacy / LLM path tests ──

def test_no_legacy_rule_translator_in_module():
    """modules/config_translation does not contain legacy_rule_translator."""
    import os as _os
    from backend.core.settings import NETWORK_AGENT_ROOT
    mod_dir = _os.path.join(NETWORK_AGENT_ROOT, "modules", "config_translation")
    for root, dirs, files in _os.walk(mod_dir):
        for f in files:
            assert "legacy_rule_translator" not in f.lower(), \
                f"legacy_rule_translator found: {_os.path.join(root, f)}"
