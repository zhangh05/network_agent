# skills/config_translation/adapter.py
"""Adapter for config_translation skill — wraps /api/translate calls."""

import json
import urllib.request
import urllib.error
from typing import Optional


_TRANSLATE_URL = "http://127.0.0.1:8010/api/translate"


def call_translate(
    source_config: str,
    source_vendor: str = "auto",
    target_vendor: str = "huawei",
    endpoint: Optional[str] = None,
) -> dict:
    """Call the translation endpoint and return the full response."""
    url = endpoint or _TRANSLATE_URL
    payload = json.dumps({
        "source_config": source_config,
        "source_vendor": source_vendor,
        "target_vendor": target_vendor,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


# Re-export for convenience
translate_config = call_translate
