# modules/config_translation/core/__init__.py
# Minimal init — RuleBasedTranslator is the sole public entry point.
# No GraphAgent / LLM / retired fallback path.

from modules.config_translation.core.rule_translator import RuleBasedTranslator

__all__ = ["RuleBasedTranslator"]
