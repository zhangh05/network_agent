# backend/api/modules.py

import json
import os
from flask import jsonify
from backend.core.paths import NETWORK_AGENT_ROOT


_MODULES_DIR = NETWORK_AGENT_ROOT / "modules"
_REGISTRY_CACHE = None


def _load_registry():
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    path = os.path.join(_MODULES_DIR, "registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            _REGISTRY_CACHE = json.load(f)
    except Exception:
        _REGISTRY_CACHE = {"version": "0.1.0", "modules": []}
    return _REGISTRY_CACHE


def handle_modules():
    return jsonify(_load_registry())


def handle_module_status(module_name):
    registry = _load_registry()
    for m in registry.get("modules", []):
        if m.get("module_name") == module_name:
            return jsonify(m)
    return jsonify({"error": f"module {module_name} not found"}), 404
