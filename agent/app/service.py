# agent/app/service.py
"""AgentApp service — global instance management."""

from agent.app.facade import AgentApp

_app_instance = None


def get_default_agent_app() -> AgentApp:
    global _app_instance
    if _app_instance is None:
        _app_instance = AgentApp()
    return _app_instance


def reset_agent_app_for_tests():
    global _app_instance
    _app_instance = None
