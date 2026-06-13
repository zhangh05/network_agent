# agent/runtime/cache.py
"""TTL cache layer with LRU eviction for web.fetch / web.search results.

Provides thread-safe caching with configurable TTL and max size.
WebCache extends TTLCache with web-specific key normalization.
"""

import time
import threading
import json
from collections import OrderedDict

# Singleton
_web_cache = None


class TTLCache:
    """Simple TTL cache with OrderedDict-based LRU eviction.

    When the cache exceeds max_size, the least recently used entry is evicted.
    Entries expire after ttl_seconds.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        """Get a cached value by key. Returns None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            age = time.time() - entry["_t"]
            if age > self._ttl:
                del self._store[key]
                return None
            # Move to end for LRU
            self._store.move_to_end(key)
            return entry["_v"]

    def set(self, key: str, value):
        """Set a cached value. Evicts LRU entry if max_size exceeded."""
        with self._lock:
            # If key exists, update and move to end
            if key in self._store:
                self._store[key] = {"_v": value, "_t": time.time()}
                self._store.move_to_end(key)
                return
            # Check size before inserting
            while len(self._store) >= self._max_size:
                self._store.popitem(last=False)  # pop oldest (LRU)
            self._store[key] = {"_v": value, "_t": time.time()}

    def clear(self):
        """Remove all cached entries."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Return current number of cached entries."""
        with self._lock:
            return len(self._store)


class WebCache(TTLCache):
    """Cache for web.fetch / web.search results.

    Extends TTLCache with web-specific key normalization and
    additional helper methods for web result caching.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        super().__init__(max_size=max_size, ttl_seconds=ttl_seconds)

    @staticmethod
    def normalize_key(url_or_query: str) -> str:
        """Normalize a URL or search query for cache key."""
        key = url_or_query.strip().lower()
        # Strip trailing slashes for URLs
        if key.startswith(("http://", "https://")):
            key = key.rstrip("/")
        return key

    def get_web(self, url_or_query: str):
        """Get a cached web result with normalized key."""
        return self.get(self.normalize_key(url_or_query))

    def set_web(self, url_or_query: str, value):
        """Set a cached web result with normalized key."""
        self.set(self.normalize_key(url_or_query), value)


def get_web_cache() -> WebCache:
    """Get or create the singleton WebCache instance."""
    global _web_cache
    if _web_cache is None:
        _web_cache = WebCache(max_size=100, ttl_seconds=300)
    return _web_cache
