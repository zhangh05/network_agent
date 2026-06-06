# backend/api/skills.py

import json
import os
from flask import jsonify
from backend.core.paths import SKILLS_DIR


_REGISTRY_CACHE = None


def _load_registry():
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE

    path = os.path.join(SKILLS_DIR, "registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            _REGISTRY_CACHE = json.load(f)
    except Exception:
        _REGISTRY_CACHE = {"version": "0.1.0", "skills": []}
    return _REGISTRY_CACHE


def handle_skills():
    return jsonify(_load_registry())


def get_skill_count() -> int:
    registry = _load_registry()
    return len(registry.get("skills", []))
