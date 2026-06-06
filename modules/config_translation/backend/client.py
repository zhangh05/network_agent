# RETIRED: modules/config_translation/backend/client.py
# This is dead code — not imported or used anywhere.
# The import below refers to backend/services/config_translation which does not exist.
# backend/services/config_translation/client.py
"""HTTP client for config translation — used by external callers."""

import json
import urllib.request
import urllib.error
from backend.services.config_translation.schemas import TranslateRequest, TranslateResponse


def translate_via_http(req: TranslateRequest, endpoint: str = "http://127.0.0.1:8010/api/translate") -> TranslateResponse:
    """Call the translation endpoint via HTTP."""
    payload = json.dumps(req.as_dict()).encode("utf-8")
    http_req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(http_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode("utf-8"))

    return TranslateResponse(
        deployable_config=data.get("deployable_config", ""),
        manual_review=data.get("manual_review", []),
        manual_review_items=data.get("manual_review_items", []),
        semantic_near=data.get("semantic_near", []),
        unsupported=data.get("unsupported", []),
        audit=data.get("audit", {}),
        manual_review_count=data.get("manual_review_count", 0),
        semantic_near_count=data.get("semantic_near_count", 0),
        unsupported_count=data.get("unsupported_count", 0),
        build_commit=data.get("build_commit", ""),
        translator_entry=data.get("translator_entry", "translate_bundle"),
    )
