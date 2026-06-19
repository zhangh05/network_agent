# agent/runtime/tool_execution/output_policy.py
"""Output policy check for final responses."""


def check_output_policy(final_response, turn) -> bool:
    """Check output policy and append warning if needed. Returns True if OK."""
    try:
        from prompts.policy import check_prompt_output
        out_result = check_prompt_output(final_response)
        if not out_result.is_ok:
            turn.warnings.append(f"output_policy_failed: {out_result.issues}")
            return False
        return True
    except Exception:
        return True
