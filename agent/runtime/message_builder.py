"""Message builder — construct the initial message list for each turn.

v3.3: Slimmed down. Delegates to PromptCompiler for assembly.
Helper functions moved to:
- cognition/scene_decision.py (_is_pure_greeting, _looks_like_tool_query)
- prompting/safe_context_renderer.py (safe_context_prompt_text → render_safe_context)
- prompting/history_renderer.py (_build_user_content_with_images)
"""

from agent.runtime.prompting.compiler import PromptCompiler


_compiler = PromptCompiler()


def build_initial_messages(context, services) -> list:
    """Build initial message list — delegates to PromptCompiler."""
    return _compiler.compile(context, services)
