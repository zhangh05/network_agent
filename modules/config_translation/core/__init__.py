# modules/config_translation/core/__init__.py
# Minimal init — RuleBasedTranslator is the sole public entry point.
# Deterministic configuration translation core.

from modules.config_translation.core.rule_translator import RuleBasedTranslator

__all__ = ["RuleBasedTranslator"]
