"""Design Purity & Anti-Regression Hard Cleanup Tests — v0.1

Strict anti-regression gates. If any prohibited item is introduced or restored,
these tests WILL fail. This is intentional.

Tests cover:
  - No prohibited API paths (/api/translate)
  - No prohibited code paths (backend/services/config_translation, GraphAgent, network-translator)
  - No prohibited ports (8020)
  - No prohibited default models (MiniMax-M1)
  - No prohibited Tool Runtime types (external_tool as current)
  - No prohibited Tool Runtime fields (tool_calls/tool_results as primary)
  - No forbidden tool handlers (ssh.exec, telnet.exec, ...)
  - No public Tool HTTP API
  - No UI tool invocation
  - No deployable claims in UI
  - Docs use current architecture (not old framework)
  - Current API entry points present
  - Current module and model defaults correct
"""

import os
import sys
import re
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {'.git', '__pycache__', '.pytest_cache', 'venv', '.venv',
                'node_modules', 'workspaces', 'runtime', 'legacy'}
# Test files reference old names for anti-regression assertions — skip them
EXCLUDE_DIRS_SCAN = EXCLUDE_DIRS | {'harness', 'scripts'}


def _scan_py_files() -> list:
    """Yield all .py files excluding dirs."""
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS_SCAN]
        for f in files:
            if f.endswith('.py'):
                yield Path(root) / f


def _scan_all_files(exts=None) -> list:
    ext_set = set(exts) if exts else None
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS_SCAN]
        for f in files:
            if ext_set and not any(f.endswith(e) for e in ext_set):
                continue
            yield Path(root) / f


def _read(path):
    return Path(path).read_text(encoding='utf-8', errors='ignore')


# ══════════════════════════════════════════════════
# Prohibited API Paths
# ══════════════════════════════════════════════════

class TestProhibitedAPIPaths:
    def test_no_api_translate_route_in_backend(self):
        """backend/main.py must NOT register /api/translate."""
        c = _read(PROJECT_ROOT / 'backend' / 'main.py')
        assert "route('/api/translate'" not in c.replace(' ', ''), (
            "/api/translate route found in backend/main.py — retired surface"
        )
        assert 'route("/api/translate"' not in c.replace(' ', ''), (
            "/api/translate route found in backend/main.py — retired surface"
        )

    def test_no_api_translate_in_frontend(self):
        """frontend/index.html must NOT call /api/translate."""
        c = _read(PROJECT_ROOT / 'frontend' / 'index.html')
        assert '/api/translate' not in c, (
            "/api/translate found in frontend — retired surface"
        )

    def test_no_api_translate_in_current_docs(self):
        """README.md must NOT list /api/translate as formal entry."""
        c = _read(PROJECT_ROOT / 'README.md')
        # /api/translate should not appear in README as a documented endpoint
        lines = [l for l in c.split('\n') if '/api/translate' in l]
        for line in lines:
            if 'legacy' not in line.lower() and 'retired' not in line.lower() and 'deprecat' not in line.lower():
                pytest.fail(f"README mentions /api/translate without legacy/deprecated context: {line.strip()}")


# ══════════════════════════════════════════════════
# Prohibited Code Paths
# ══════════════════════════════════════════════════

class TestProhibitedCodePaths:
    def test_no_backend_services_config_translation(self):
        """backend/services/config_translation must not exist as active code."""
        path = PROJECT_ROOT / 'backend' / 'services' / 'config_translation.py'
        if path.exists():
            pytest.fail(f"{path} exists — retired code path")

    def test_no_import_backend_services_config_translation(self):
        """No active .py file imports backend.services.config_translation."""
        for py_file in _scan_py_files():
            content = _read(py_file)
            # Skip files marked as RETIRED or DEAD CODE
            if 'RETIRED' in content[:200] or 'DEAD CODE' in content[:200]:
                continue
            for line in content.split('\n'):
                stripped = line.strip()
                # Skip comments and docstrings
                if stripped.startswith('#') or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                if 'backend.services.config_translation' in stripped.replace(' ', ''):
                    pytest.fail(f"{py_file} imports backend.services.config_translation")

    def test_no_import_network_translator(self):
        """No active .py file imports network-translator."""
        for py_file in _scan_py_files():
            content = _read(py_file)
            # Skip validator.py — it checks FOR prohibited imports (anti-regression)
            if 'validator' in str(py_file).lower() or 'Retired' in content[:200]:
                continue
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                if 'network-translator' in stripped and ('import' in stripped or 'from ' in stripped):
                    pytest.fail(f"{py_file} imports network-translator")

    def test_no_import_graphagent(self):
        """No active .py file imports GraphAgent."""
        for py_file in _scan_py_files():
            content = _read(py_file)
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                if 'GraphAgent' in stripped and ('import' in stripped or 'from ' in stripped):
                    pytest.fail(f"{py_file} imports GraphAgent")


# ══════════════════════════════════════════════════
# Prohibited Port / Model Defaults
# ══════════════════════════════════════════════════

class TestProhibitedDefaults:
    def test_no_8020_as_current_port(self):
        """backend/main.py must not default to port 8020."""
        c = _read(PROJECT_ROOT / 'backend' / 'main.py')
        assert '8020' not in c, "Port 8020 found in backend/main.py — prohibited"

    def test_no_8020_in_frontend(self):
        """frontend must not reference port 8020."""
        c = _read(PROJECT_ROOT / 'frontend' / 'index.html')
        assert '8020' not in c, "Port 8020 found in frontend — prohibited"

    def test_no_minimax_m1_as_default_model(self):
        """No config sets MiniMax-M1 as default model."""
        llm_yaml = PROJECT_ROOT / 'config' / 'llm.yaml'
        if llm_yaml.exists():
            c = _read(llm_yaml)
            if 'MiniMax-M1' in c:
                # Check context — must not be the default model line
                for line in c.split('\n'):
                    if 'MiniMax-M1' in line and 'default' in line.lower():
                        pytest.fail(f"MiniMax-M1 set as default in {llm_yaml}: {line.strip()}")

    def test_minimax_m3_is_default(self):
        """config/llm.yaml should default to MiniMax-M3."""
        llm_yaml = PROJECT_ROOT / 'config' / 'llm.yaml'
        if llm_yaml.exists():
            c = _read(llm_yaml)
            assert 'MiniMax-M3' in c, "MiniMax-M3 must appear in llm.yaml"

    def test_no_minimax_m1_in_frontend(self):
        """Frontend must not show MiniMax-M1 as default."""
        c = _read(PROJECT_ROOT / 'frontend' / 'index.html')
        assert 'MiniMax-M1' not in c, "MiniMax-M1 found in frontend — prohibited"


# ══════════════════════════════════════════════════
# Tool Runtime Prohibited Types / Fields
# ══════════════════════════════════════════════════

class TestToolRuntimeProhibited:
    def test_external_tool_is_legacy(self):
        """external_tool must be marked deprecated/legacy in registry/schemas.py."""
        c = _read(PROJECT_ROOT / 'registry' / 'schemas.py')
        assert 'deprecat' in c.lower() or 'legacy' in c.lower(), (
            "external_tool must be marked deprecated/legacy in registry/schemas.py"
        )

    def test_external_tool_not_current_tool_type(self):
        """docs must not describe external_tool as current Tool Runtime type."""
        docs_to_check = [
            'docs/TOOL_RUNTIME.md',
            'docs/TOOL_RUNTIME_INTEGRATION.md',
        ]
        for doc in docs_to_check:
            path = PROJECT_ROOT / doc
            if path.exists():
                c = _read(path)
                if 'external_tool' in c:
                    # Must appear only in deprecated/legacy context
                    context_start = max(0, c.index('external_tool') - 50)
                    context_end = min(len(c), c.index('external_tool') + 50)
                    ctx = c[context_start:context_end].lower()
                    assert any(w in ctx for w in ['deprecat', 'legacy', 'not', 'do not']), (
                        f"{doc}: external_tool mentioned without deprecated context"
                    )

    def test_tool_runtime_not_use_legacy_tool_calls(self):
        """tool_runtime/ must not import or use tool_calls from agent/state."""
        import importlib, inspect
        tr_modules = ['tool_runtime.schemas', 'tool_runtime.client',
                      'tool_runtime.context', 'tool_runtime.integration']
        for mod_name in tr_modules:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            assert 'from agent.state import' not in source, (
                f"{mod_name} imports from agent.state"
            )

    def test_tool_invocation_result_are_primary(self):
        """Tool Runtime uses ToolInvocation/ToolResult, not legacy tool_calls/tool_results."""
        import tool_runtime.schemas
        assert hasattr(tool_runtime.schemas, 'ToolInvocation')
        assert hasattr(tool_runtime.schemas, 'ToolResult')


# ══════════════════════════════════════════════════
# Forbidden Tool Handlers
# ══════════════════════════════════════════════════

class TestForbiddenToolHandlers:

    FORBIDDEN = [
        'ssh.exec', 'telnet.exec', 'snmp.walk', 'nmap.scan',
        'ping.sweep', 'command.exec', 'shell.exec', 'config.push',
    ]

    def test_no_forbidden_handler_in_builtins(self):
        """builtins.py must not have handlers for forbidden tools."""
        c = _read(PROJECT_ROOT / 'tool_runtime' / 'builtins.py')
        for tid in self.FORBIDDEN:
            assert tid not in c or 'BUILTIN_TOOLS' not in c.split(tid)[-1][:50], (
                f"Handler found for forbidden tool: {tid}"
            )

    def test_forbidden_tools_only_in_policy_and_docs(self):
        """Forbidden tool IDs must only appear in policy, docs forbidden sections, or tests."""
        allowed_files = {
            str(PROJECT_ROOT / 'tool_runtime' / 'policy.py'),
            str(PROJECT_ROOT / 'docs' / 'TOOL_RUNTIME.md'),
            str(PROJECT_ROOT / 'docs' / 'TOOL_RUNTIME_INTEGRATION.md'),
            str(PROJECT_ROOT / 'docs' / 'MODULE_SKILL_TOOL_MODEL.md'),
        }
        for tid in self.FORBIDDEN:
            for py_file in _scan_py_files():
                path_str = str(py_file)
                # Skip test files and allowed files
                if 'test_' in path_str or path_str in allowed_files:
                    continue
                content = _read(py_file)
                if tid in content:
                    # Check if it's a handler registration
                    if 'def handler' in content or 'lambda inv' in content or 'register_tool' in content:
                        pytest.fail(f"{py_file}: possible handler for forbidden tool {tid}")

    def test_all_forbidden_in_policy_block(self):
        """All forbidden tool IDs must be in V01_FORBIDDEN_TOOLS."""
        c = _read(PROJECT_ROOT / 'tool_runtime' / 'policy.py')
        for tid in self.FORBIDDEN:
            assert tid in c, f"{tid} not in V01_FORBIDDEN_TOOLS"


# ══════════════════════════════════════════════════
# Public Tool HTTP API Safety Contract
# ══════════════════════════════════════════════════

class TestPublicToolAPISafetyContract:
    def test_tool_routes_live_in_runtime_routes(self):
        """Tool HTTP API routes must stay isolated in runtime_routes."""
        c = _read(PROJECT_ROOT / 'backend' / 'main.py')
        runtime = _read(PROJECT_ROOT / 'backend' / 'api' / 'runtime_routes.py')
        assert '/api/tools' not in c, "Tool routes must not be registered directly in backend/main.py"
        assert '@app.route("/api/tools/invoke", methods=["POST"])' in runtime
        assert '_validate_approved_tool_invocation' in runtime

    def test_frontend_uses_tool_invoke_api_not_legacy_helper(self):
        """frontend may call v0.3 tool APIs but must not use legacy invoke_tool helpers."""
        c = _read(PROJECT_ROOT / 'frontend' / 'index.html')
        # tool_runtime may appear in:
        # 1. zhMap translation for system health panel
        # 2. _SENSITIVE_KEYS array (but tool_runtime is not a secret key name)
        # Count total occurrences and subtract whitelisted ones
        total = c.count('tool_runtime')
        zhmap_occ = c.count("tool_runtime:'工具'")
        # +1 for legitimate component name check in runtime health display
        allowed_extra = 1
        assert total - zhmap_occ <= allowed_extra, f"tool_runtime referenced {total - zhmap_occ} times outside zhMap (allowed: {allowed_extra})"
        assert 'invoke_tool' not in c, "invoke_tool referenced in frontend"
        assert '/api/tools/invoke' in c, "v0.3 Tool Invoke UI should call the protected API endpoint"


# ══════════════════════════════════════════════════
# UI Safety Claims
# ══════════════════════════════════════════════════

class TestUISafety:
    def test_no_deployable_claim_in_ui(self):
        """UI must not claim config is directly deployable."""
        c = _read(PROJECT_ROOT / 'frontend' / 'index.html')
        assert '可直接下发' not in c, "可直接下发 found in UI"
        assert '直接下发' not in c, "直接下发 found in UI"


# ══════════════════════════════════════════════════
# Current Architecture Verification
# ══════════════════════════════════════════════════

class TestCurrentArchitecture:
    def test_config_translation_main_chain(self):
        """config_translation entry point is modules/config_translation."""
        path = PROJECT_ROOT / 'modules' / 'config_translation' / 'backend' / 'service.py'
        assert path.exists(), "config_translation service.py missing"

    def test_translate_bundle_exists(self):
        """translate_bundle must exist in config_translation."""
        # Search for translate_bundle in service.py
        c = _read(PROJECT_ROOT / 'modules' / 'config_translation' / 'backend' / 'service.py')
        assert 'translate_bundle' in c or 'translate_config' in c, (
            "translate_bundle not found in config_translation service"
        )

    def test_only_config_translation_enabled(self):
        """Only config_translation and knowledge_base modules should be enabled."""
        from registry.loader import load_module_registry
        mods = load_module_registry()
        enabled = sorted([m.module_name for m in mods if m.is_enabled()])
        assert enabled == sorted(['config_translation', 'knowledge_base']), (
            f"Unexpected enabled modules: {enabled}"
        )

    def test_current_api_entries_present(self):
        """Backend must have the 3 current formal API entries."""
        c = _read(PROJECT_ROOT / 'backend' / 'main.py')
        assert '/api/agent/run' in c, "Missing /api/agent/run"
        assert '/api/modules/config-translation/translate' in c, "Missing translate API"
        assert '/api/jobs' in c, "Missing /api/jobs"

    def test_no_graphagent_in_agent(self):
        """agent/ directory must not contain GraphAgent code."""
        for py_file in _scan_py_files():
            if 'agent/' not in str(py_file) and 'agent\\' not in str(py_file):
                continue
            c = _read(py_file)
            for line in c.split('\n'):
                stripped = line.strip()
                # Skip comments (e.g. "# No GraphAgent")
                if stripped.startswith('#'):
                    continue
                if 'GraphAgent' in stripped and 'retired' not in stripped.lower():
                    if 'import' in stripped or 'from ' in stripped:
                        pytest.fail(f"GraphAgent import in {py_file}")


# ══════════════════════════════════════════════════
# Doc Architecture Verification
# ══════════════════════════════════════════════════

class TestDocArchitecture:
    def test_readme_has_current_entry(self):
        """README must reference current API entries."""
        c = _read(PROJECT_ROOT / 'README.md')
        assert '/api/agent/run' in c or 'agent/run' in c

    def test_readme_no_graphagent(self):
        """README must not reference GraphAgent as current."""
        c = _read(PROJECT_ROOT / 'README.md')
        assert 'GraphAgent' not in c, "GraphAgent in README — prohibited"

    def test_readme_no_network_translator(self):
        """README must not reference network-translator as current dependency."""
        c = _read(PROJECT_ROOT / 'README.md')
        assert 'network-translator' not in c, "network-translator in README — prohibited"

    def test_foundation_baseline_no_llm_skeleton(self):
        """FOUNDATION_BASELINE must not describe LLM as skeleton."""
        path = PROJECT_ROOT / 'docs' / 'FOUNDATION_BASELINE.md'
        if path.exists():
            c = _read(path)
            assert 'LLM skeleton' not in c, "LLM skeleton in FOUNDATION_BASELINE"

    def test_foundation_baseline_no_unresolved_job(self):
        """FOUNDATION_BASELINE must not describe Job as unresolved."""
        path = PROJECT_ROOT / 'docs' / 'FOUNDATION_BASELINE.md'
        if path.exists():
            c = _read(path)
            assert 'unresolved' not in c.lower() and '未收口' not in c, (
                "Job unresolved in FOUNDATION_BASELINE"
            )

    def test_prompt_runtime_not_defaulting_to_old_prompts(self):
        """prompts loader must not default to old PROMPTS path."""
        path = PROJECT_ROOT / 'prompts' / 'loader.py'
        if path.exists():
            c = _read(path)
            # Must reference registry.yaml, not old hardcoded PROMPTS
            assert 'registry.yaml' in c, "Prompt loader must use registry.yaml"


# ══════════════════════════════════════════════════
# Tool Runtime Client Safety
# ══════════════════════════════════════════════════

class TestClientSafety:
    def test_client_no_llm(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert 'from agent.llm' not in body, "client.py imports LLM"

    def test_client_no_memory(self):
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert 'from memory' not in body, "client.py imports Memory"

    def test_client_policy_not_bypassed(self):
        """Client must not offer any bypass method."""
        import tool_runtime.client
        import inspect
        source = inspect.getsource(tool_runtime.client)
        body = source.split('"""')[2] if '"""' in source else source
        assert 'bypass_policy' not in body and 'skip_policy' not in body, (
            "Client offers policy bypass methods"
        )

    def test_trace_metadata_no_full_output(self):
        from tool_runtime.schemas import ToolResult
        from tool_runtime.integration import build_trace_metadata_from_tool_result
        result = ToolResult(invocation_id='inv', tool_id='t', status='succeeded',
                            output={'secret': 'hidden_value'})
        meta = build_trace_metadata_from_tool_result(result)
        assert 'hidden_value' not in str(meta), "Secret value leaked into trace metadata"

    # ── Knowledge Search Registry & Adapter Safety ──

    def test_knowledge_search_skill_enabled_in_registry(self):
        """knowledge_search skill must be enabled in registry."""
        from registry.loader import load_skill_registry
        skills = load_skill_registry()
        ks = [s for s in skills if s.skill_name == 'knowledge_search']
        assert len(ks) == 1, f"Expected 1 knowledge_search skill, got {len(ks)}"
        assert ks[0].is_enabled(), "knowledge_search skill is not enabled"

    def test_knowledge_search_adapter_no_llm_import(self):
        """knowledge_search adapter must NOT import any LLM provider."""
        import inspect
        from skills.knowledge_search import adapter
        source = inspect.getsource(adapter)
        assert 'from agent.llm' not in source, "adapter imports LLM module"
        assert 'safe_generate' not in source, "adapter calls LLM safe_generate"
        assert 'resolve_provider' not in source, "adapter calls LLM provider resolution"
        assert 'minimax' not in source.lower(), "adapter references LLM provider"
        assert 'openai' not in source.lower(), "adapter references LLM provider"

    def test_knowledge_search_adapter_calls_loader(self):
        """knowledge_search adapter must call knowledge_loader."""
        import inspect
        from skills.knowledge_search import adapter
        source = inspect.getsource(adapter)
        assert 'load_knowledge_context' in source, "adapter must call load_knowledge_context"

    def test_enabled_modules_are_config_translation_and_knowledge_base(self):
        """Enabled modules must be exactly config_translation and knowledge_base."""
        from registry.loader import load_module_registry
        mods = load_module_registry()
        enabled = sorted([m.module_name for m in mods if m.is_enabled()])
        assert enabled == sorted(['config_translation', 'knowledge_base']), (
            f"Wrong enabled modules: {enabled}"
        )

    def test_topology_and_inspection_still_planned(self):
        """Topology and inspection modules must remain planned."""
        from registry.loader import load_module_registry
        mods = load_module_registry()
        planned = {m.module_name: m.maturity for m in mods if not m.is_enabled()}
        assert 'topology' in planned, "topology not found in modules"
        assert planned['topology'] == 'planned', f"topology maturity: {planned.get('topology')}"
        assert 'inspection' in planned, "inspection not found in modules"
        assert planned['inspection'] == 'planned', f"inspection maturity: {planned.get('inspection')}"

    def test_knowledge_query_graph_has_result_details(self):
        """Agent graph response must include knowledge_result_details for frontend display."""
        from agent.graph import run_agent
        result = run_agent(
            user_input='查一下知识库里辣椒炒肉是什么',
            intent='', payload={}, workspace_id='default', session_id='',
        )
        assert result['intent'] == 'knowledge_query'
        details = result.get('knowledge_result_details', [])
        assert isinstance(details, list), "knowledge_result_details must be a list"
        if not result.get('knowledge_not_found'):
            assert len(details) > 0, "Should have result details when found"
            for d in details:
                assert 'title' in d, "each detail must have title"
                assert 'artifact_id' in d, "each detail must have artifact_id"
                assert 'chunk_id' in d, "each detail must have chunk_id"
                assert 'sensitivity' in d, "each detail must have sensitivity"
                # No full content / secrets
                assert 'deployable_config' not in d, "detail must not have deployable_config"
                assert 'password' not in str(d).lower(), "detail must not have password"

    def test_knowledge_query_not_found_response_safe(self):
        """Not-found response must NOT contain paths, secrets, or full config."""
        from agent.graph import run_agent
        result = run_agent(
            user_input='zzz_no_such_thing_xyz_999',
            intent='', payload={}, workspace_id='default', session_id='',
        )
        fr = result.get('final_response', '')
        # Must not leak paths
        assert '/Users/' not in fr, "Not-found response contains filesystem path"
        # Must not leak secrets
        assert 'password' not in fr.lower(), "Not-found response contains password"
        assert 'api_key' not in fr.lower(), "Not-found response contains api_key"
        # Must be not_found
        if result['intent'] == 'knowledge_query':
            assert result.get('knowledge_not_found', True), "Expected not_found for nonexistent query"
