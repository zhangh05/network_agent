# harness/test_prompt_policy_negation_context.py
"""Test negation context detection in prompt output and LLM response policy.

Tests that safe disclaimers pass while dangerous positive claims are blocked.
"""

import sys
from pathlib import Path

NETWORK_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(NETWORK_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(NETWORK_AGENT_DIR))

import pytest


# ── prompt output policy (check_prompt_output) ──

class TestPromptOutputNegationContext:
    """Test prompts/policy.py check_prompt_output with negation context."""

    @pytest.fixture
    def check(self):
        from prompts.policy import check_prompt_output
        return check_prompt_output

    def test_disclaimer_not_deployable_passes(self, check):
        """我不会声称配置可直接下发。"""
        text = "生成的翻译结果需要人工复核，我不会声称配置可直接下发。"
        r = check(None, text)
        assert r.ok, f"Safe disclaimer blocked: {r.issues}"

    def test_disclaimer_not_production_ready_passes(self, check):
        """不要把翻译结果当作可直接部署的配置。"""
        text = "注意：不要把翻译结果当作可直接部署的配置，请人工确认后再使用。"
        r = check(None, text)
        assert r.ok, f"Safe disclaimer blocked: {r.issues}"

    def test_disclaimer_manual_review_required_passes(self, check):
        """生产使用前仍需人工复核。"""
        text = "翻译已完成，但生产使用前仍需人工复核。配置中的风险项已标出。"
        r = check(None, text)
        assert r.ok, f"Safe disclaimer blocked: {r.issues}"

    def test_cannot_generate_deployable_passes(self, check):
        """我不能生成 deployable_config。"""
        text = "抱歉，根据安全策略，我不能生成 deployable_config。请使用配置翻译模块。"
        r = check(None, text)
        assert r.ok, f"Safe disclaimer blocked: {r.issues}"

    def test_no_secrets_output_passes(self, check):
        """我不会输出密码或 token。"""
        text = "安全提示：我不会输出密码、token、API key 或任何敏感凭证。"
        r = check(None, text)
        assert r.ok, f"Safe disclaimer blocked: {r.issues}"


class TestPromptOutputDangerousClaims:
    """Test that actual dangerous claims ARE blocked."""

    @pytest.fixture
    def check(self):
        from prompts.policy import check_prompt_output
        return check_prompt_output

    def test_direct_deploy_claim_blocked(self, check):
        """这个配置可以直接下发。"""
        text = "翻译完成，这个配置可以直接下发到生产环境。"
        r = check(None, text)
        assert not r.ok, f"Dangerous claim should be blocked: {r.issues}"

    def test_no_manual_review_claim_blocked(self, check):
        """无需人工复核。"""
        text = "配置翻译结果经 AI 验证无误，无需人工复核，可以直接使用。"
        r = check(None, text)
        assert not r.ok, f"Dangerous claim should be blocked: {r.issues}"

    def test_ready_to_deploy_claim_blocked(self, check):
        """可以直接部署到生产环境。"""
        text = "该配置经过完整验证，ready to deploy，可以直接部署到生产环境。"
        r = check(None, text)
        assert not r.ok, f"Dangerous claim should be blocked: {r.issues}"

    def test_deployable_config_code_block_blocked(self, check):
        """这是最终 deployable_config。"""
        text = "以下是最终 deployable_config：\n```\nsysname CoreSwitch\ninterface Vlanif100\n ip address 10.0.0.1 255.255.255.0\n```\n可直接下发。"
        r = check(None, text)
        assert not r.ok, f"Dangerous claim should be blocked: {r.issues}"

    def test_secrets_leak_blocked(self, check):
        """Password or token leaked in output. Use policy-detectable patterns."""
        text = "The device uses password: admin123 and token: abcdef1234567890."
        r = check(None, text)
        assert not r.ok, f"Secrets leak should be blocked: {r.issues}"


# ── LLM response policy (check_response) ──

class TestLLMResponseNegationContext:
    """Test agent/llm/policy.py check_response with negation context."""

    @pytest.fixture
    def check_response(self):
        from agent.llm.policy import check_response
        return check_response

    def test_disclaimer_safe_in_response(self, check_response):
        """我不会声称可直接下发 → passes response check."""
        from agent.llm.schemas import LLMResponse
        resp = LLMResponse(content="需要提醒的是：我不会声称这些配置可直接下发，使用前务必人工审核。")
        r = check_response(resp)
        assert r.allowed, f"Safe response blocked: {r.reason}"

    def test_dangerous_claim_blocked_in_response(self, check_response):
        """可直接下发 → blocked by response check."""
        from agent.llm.schemas import LLMResponse
        resp = LLMResponse(content="配置翻译完毕，可直接下发到设备上。")
        r = check_response(resp)
        assert not r.allowed, f"Dangerous response should be blocked: {r.reason}"

    def test_multiple_negations_still_safe(self, check_response):
        """Multiple negation phrases still pass."""
        from agent.llm.schemas import LLMResponse
        resp = LLMResponse(content=(
            "关于部署：我不会声称配置可直接下发。\n"
            "你也不要把结果当作 ready to deploy 的配置。\n"
            "所有人工复核项都标注出来了。"
        ))
        r = check_response(resp)
        assert r.allowed, f"Multi-negation response blocked: {r.reason}"


# ── Negation context helper unit tests ──

class TestIsNegationContext:
    """Unit test _is_negation_context directly."""

    @pytest.fixture
    def is_negation(self):
        from prompts.policy import _is_negation_context
        return _is_negation_context

    def test_cn_negation_bu_hui(self, is_negation):
        text = "我不会声称可直接下发。"
        idx = text.find("可直接下发")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_cn_negation_bu_yao(self, is_negation):
        text = "不要把结果当作可直接部署的。"
        idx = text.find("可直接部署")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_cn_negation_jue_bu(self, is_negation):
        text = "我绝不声称可直接下发。"
        idx = text.find("可直接下发")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_cn_negation_jin_zhi(self, is_negation):
        text = "禁止声称可直接下发到设备。"
        idx = text.find("可直接下发")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_en_negation_not(self, is_negation):
        text = "not ready to deploy."
        idx = text.lower().find("ready to deploy")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_en_negation_never(self, is_negation):
        text = "Never use ready to deploy claims."
        idx = text.lower().find("ready to deploy")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_en_negation_dont(self, is_negation):
        text = "Don't say ready to deploy."
        idx = text.lower().find("ready to deploy")
        assert idx > 0
        assert is_negation(text, idx) is True

    def test_no_negation_returns_false(self, is_negation):
        """Positive claim without negation → False."""
        text = "配置可直接下发到生产环境。"
        idx = text.find("可直接下发")
        assert idx > 0
        assert is_negation(text, idx) is False

    def test_no_negation_en_returns_false(self, is_negation):
        """Positive claim without EN negation → False."""
        text = "The configuration is ready to deploy immediately."
        idx = text.lower().find("ready to deploy")
        assert idx > 0
        assert is_negation(text, idx) is False

    def test_no_negation_password_leak(self, is_negation):
        """Password leak without negation → False."""
        text = "ssh password admin123"
        idx = text.find("password")
        assert idx >= 0
        # The password pattern itself is not negation-context dependent
        # but _is_negation_context should return False here
        assert is_negation(text, idx) is False

    def test_negation_not_too_far_away(self, is_negation):
        """Negation > 12 chars away → False (too far)."""
        text = "不这是一个很长的前缀来说明上下文然后再来一个可直接下发。"
        idx = text.find("可直接下发")
        assert idx > 0
        # "不" is at pos 0, "可直接下发" is far away
        # The distance between chars is too large
        assert is_negation(text, idx) is False
