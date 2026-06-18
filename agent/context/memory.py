# agent/context/memory.py
"""In-memory workspace store (stub for future persistence)."""


class MemoryStore:
    def __init__(self):
        self._store = {}

    def get(self, key: str, default=None):
        return self._store.get(key, default)

    def set(self, key: str, value):
        self._store[key] = value
