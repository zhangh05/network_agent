# backend/api/version.py

from backend.core.settings import (
    APP_NAME, BUILD_COMMIT, TRANSLATOR_ENTRY, API_MODE,
    SWITCH_ROUTER_STATUS, PRODUCT_READY, FIREWALL_STATUS,
)


def get_version():
    return {
        "app": APP_NAME,
        "build_commit": BUILD_COMMIT,
        "translator_entry": TRANSLATOR_ENTRY,
        "switch_router_status": SWITCH_ROUTER_STATUS,
        "product_ready": PRODUCT_READY,
        "firewall_status": FIREWALL_STATUS,
        "api_mode": API_MODE,
    }
