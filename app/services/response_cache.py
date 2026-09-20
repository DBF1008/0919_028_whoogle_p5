"""Thread-safe TTL response cache.

Extracted from HttpxClient so that caching concerns (key normalization,
locking, TTL eviction) are isolated from the transport layer.
"""

import threading
from typing import Dict, Optional, Tuple

from cachetools import TTLCache

CacheKey = Tuple[str, str, Tuple[Tuple[str, str], ...]]


class ResponseCache:
    """A lock-guarded TTLCache for HTTP GET responses."""

    def __init__(self, ttl_seconds: int = 30, maxsize: int = 256) -> None:
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()

    @staticmethod
    def make_key(method: str, url: str,
                 headers: Optional[Dict[str, str]]) -> CacheKey:
        normalized_headers = tuple(sorted((headers or {}).items()))
        return (method.upper(), url, normalized_headers)

    def get(self, key: CacheKey):
        with self._lock:
            return self._cache.get(key)

    def set(self, key: CacheKey, response) -> None:
        with self._lock:
            self._cache[key] = response

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
