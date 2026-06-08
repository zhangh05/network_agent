# backend/api/version.py

from backend.core.settings import (
    APP_NAME, APP_VERSION, BUILD_COMMIT, TRANSLATOR_ENTRY, API_MODE,
    SWITCH_ROUTER_STATUS, PRODUCT_READY, FIREWALL_STATUS,
    CONFIG_TRANSLATION_SOURCE, EXTERNAL_TRANSLATOR_DEPENDENCY,
)


def get_version():
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "build_commit": BUILD_COMMIT,
        "translator_entry": TRANSLATOR_ENTRY,
        "switch_router_status": SWITCH_ROUTER_STATUS,
        "product_ready": PRODUCT_READY,
        "firewall_status": FIREWALL_STATUS,
        "api_mode": API_MODE,
        "config_translation_source": CONFIG_TRANSLATION_SOURCE,
        "external_translator_dependency": EXTERNAL_TRANSLATOR_DEPENDENCY,
    }
