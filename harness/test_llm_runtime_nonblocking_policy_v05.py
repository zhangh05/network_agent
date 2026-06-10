# harness/test_llm_runtime_nonblocking_policy_v05.py
"""LLM Runtime v0.5 — policy non-blocking tests."""

import pytest
from unittest.mock import MagicMock, patch


class TestPromptInputPolicyNonBlocking:
    """prompt_input_policy_fail_does_not_block_provider_call"""

    def test_prompt_input_policy_fail_still_calls_provider(self):
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(
            content="LLM answer despite policy failure",
            provider="mock", model="mock",
        )

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("prompts.policy.detect_prompt_injection") as mock_inj:
                    mock_inj.return_value = MagicMock(injection_detected=False, warnings=[])
                    with patch("prompts.policy.check_prompt_input") as mock_check:
                        mock_check.return_value = MagicMock(ok=False, issues=[{"rule": "input_block"}])
                        with patch("agent.llm.provider.generate", return_value=mock_resp) as mock_gen:
                            with patch("agent.llm.policy.check_request") as mock_req:
                                mock_req.return_value = MagicMock(allowed=True, violations=[])
                                from agent.llm.runtime import safe_generate
                                output = safe_generate("result_summarize", user_input="test")

                                # Key assertion: provider WAS called despite policy failure
                                mock_gen.assert_called_once()
                                assert output.llm_used is True
                                assert "despite policy failure" in output.answer

    def test_prompt_input_policy_fail_recorded_in_metadata(self):
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(content="answer", provider="mock", model="mock")

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("prompts.policy.check_prompt_input") as mock_check:
                    mock_check.return_value = MagicMock(ok=False, issues=[{"rule": "test_rule"}])
                    with patch("agent.llm.provider.generate", return_value=mock_resp):
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            meta = output.metadata or {}
                            assert meta.get("prompt_input_ok") is False


class TestPromptTextPolicyNonBlocking:
    """prompt_text_policy_fail_does_not_block_provider_call"""

    def test_prompt_text_policy_fail_still_calls_provider(self):
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(
            content="answer despite text policy fail",
            provider="mock", model="mock",
        )

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("prompts.policy.check_prompt_text") as mock_check:
                    mock_check.return_value = MagicMock(ok=False, issues=[{"rule": "text_block"}])
                    with patch("agent.llm.provider.generate", return_value=mock_resp) as mock_gen:
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            mock_gen.assert_called_once()
                            assert output.llm_used is True
                            assert "despite text policy fail" in output.answer


class TestOutputPolicyNonBlocking:
    """output_policy_fail_returns_answer_with_warning"""

    def test_output_policy_fail_still_returns_answer(self):
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(
            content="answer with output policy issue",
            provider="mock", model="mock",
        )

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("agent.llm.provider.generate", return_value=mock_resp):
                    with patch("prompts.policy.check_prompt_output") as mock_check:
                        mock_check.return_value = MagicMock(ok=False, issues=[{"rule": "output_block"}])
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            assert output.llm_used is True
                            assert "answer with output policy issue" in output.answer
                            assert len(output.warnings) > 0

    def test_output_policy_fail_metadata_has_flag(self):
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(content="answer", provider="mock", model="mock")

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("agent.llm.provider.generate", return_value=mock_resp):
                    with patch("prompts.policy.check_prompt_output") as mock_check:
                        mock_check.return_value = MagicMock(ok=False, issues=[{"rule": "r"}])
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            meta = output.metadata or {}
                            assert meta.get("output_policy_ok") is False


class TestResponsePolicyNonBlocking:
    """response_policy_fail_returns_answer_with_warning"""

    def test_response_policy_fail_still_returns_answer(self):
        from agent.llm.schemas import LLMResponse, PolicyDecision

        mock_resp = LLMResponse(
            content="answer with response policy issue",
            provider="mock", model="mock",
        )

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("agent.llm.provider.generate", return_value=mock_resp):
                    with patch("agent.llm.policy.check_response") as mock_check:
                        mock_check.return_value = PolicyDecision(allowed=False, reason="resp_block", violations=["v"])
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            assert output.llm_used is True
                            assert "answer with response policy issue" in output.answer
                            assert len(output.warnings) > 0

    def test_response_policy_fail_metadata_has_flag(self):
        from agent.llm.schemas import LLMResponse, PolicyDecision

        mock_resp = LLMResponse(content="answer", provider="mock", model="mock")

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("agent.llm.provider.generate", return_value=mock_resp):
                    with patch("agent.llm.policy.check_response") as mock_check:
                        mock_check.return_value = PolicyDecision(allowed=False, reason="r", violations=["v"])
                        with patch("agent.llm.policy.check_request") as mock_req:
                            mock_req.return_value = MagicMock(allowed=True, violations=[])
                            from agent.llm.runtime import safe_generate
                            output = safe_generate("result_summarize", user_input="test")

                            meta = output.metadata or {}
                            assert meta.get("response_policy_ok") is False


class TestSafeToShowFalseButAnswerRetained:
    """safe_to_show false but answer retained"""

    def test_safe_to_show_false_but_answer_not_emptied(self):
        """When all policies fail, safe_to_show=False but answer is NOT emptied."""
        from agent.llm.schemas import LLMResponse

        mock_resp = LLMResponse(
            content="answer even though all policies failed",
            provider="mock", model="mock",
        )

        with patch("prompts.loader.get_prompt_by_task") as mock_get_prompt:
            mock_get_prompt.return_value = MagicMock(prompt_id="p1", version="v1")
            with patch("prompts.renderer.render_prompt") as mock_render:
                mock_render.return_value = MagicMock(text="rendered")
                with patch("prompts.policy.check_prompt_input") as mock_in:
                    mock_in.return_value = MagicMock(ok=False, issues=[{"rule": "in"}])
                    with patch("prompts.policy.check_prompt_text") as mock_txt:
                        mock_txt.return_value = MagicMock(ok=False, issues=[{"rule": "txt"}])
                        with patch("prompts.policy.check_prompt_output") as mock_out:
                            mock_out.return_value = MagicMock(ok=False, issues=[{"rule": "out"}])
                            with patch("agent.llm.provider.generate", return_value=mock_resp):
                                with patch("agent.llm.policy.check_request") as mock_req:
                                    mock_req.return_value = MagicMock(allowed=True, violations=[])
                                    with patch("agent.llm.policy.check_response") as mock_resp_policy:
                                        mock_resp_policy.return_value = MagicMock(allowed=False, violations=["r"])
                                        from agent.llm.runtime import safe_generate
                                        output = safe_generate("result_summarize", user_input="test")

                                        # safe_to_show should be False
                                        assert output.safe_to_show is False
                                        # But answer must NOT be emptied
                                        assert len(output.answer) > 0
                                        assert "even though all policies failed" in output.answer
                                        # Warnings should contain policy failures
                                        assert len(output.warnings) > 0
