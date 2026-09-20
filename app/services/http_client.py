"""Thin, reusable wrapper around httpx.Client.

Responsibilities that used to be crammed into this class are delegated
to focused collaborators:

- app.services.ssl_factory: SSL verification + client construction
- app.services.retry_policy.RetryPolicy: retry/backoff decisions
- app.services.response_cache.ResponseCache: optional TTL caching

The public API (constructor signature, get(), close(), proxies) is
unchanged so existing callers keep working.
"""

import os
import time
from typing import Dict, Optional

import httpx

from app.services.response_cache import ResponseCache
from app.services.retry_policy import RetryPolicy
from app.services.ssl_factory import (
    create_client_with_ssl_fallback,
    determine_verify_setting,
)

_TRUE_VALUES = ('1', 'true', 't', 'yes', 'y')


class HttpxClient:
    """HTTP transport with retries and optional TTL caching.

    The client is intended to be safe for reuse across requests.
    Per-request overrides for headers/cookies are supported.
    """

    def __init__(
            self,
            proxies: Optional[Dict[str, str]] = None,
            timeout_seconds: float = 15.0,
            cache_ttl_seconds: int = 30,
            cache_maxsize: int = 256,
            http2: bool = True) -> None:
        # Allow disabling HTTP/2 via environment variable
        # HTTP/2 can sometimes cause protocol errors with certain servers
        if os.environ.get('WHOOGLE_DISABLE_HTTP2', '').lower() in _TRUE_VALUES:
            http2 = False

        self._proxies = proxies or {}
        self._http2 = http2
        self._timeout_seconds = timeout_seconds
        self._verify = determine_verify_setting()
        self._client, self._verify = self._new_client(self._verify)
        self._retry_policy = RetryPolicy()
        self._cache = ResponseCache(ttl_seconds=cache_ttl_seconds,
                                    maxsize=cache_maxsize)

    def _new_client(self, verify):
        """Build the underlying httpx.Client with SSL fallbacks."""
        return create_client_with_ssl_fallback(
            self._proxies,
            verify,
            http2=self._http2,
            timeout=self._timeout_seconds,
            follow_redirects=True)

    @property
    def proxies(self) -> Dict[str, str]:
        return self._proxies

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    def get(self,
            url: str,
            headers: Optional[Dict[str, str]] = None,
            cookies: Optional[Dict[str, str]] = None,
            retries: int = 2,
            backoff_seconds: float = 0.5,
            use_cache: bool = False) -> httpx.Response:
        cache_key = None
        if use_cache:
            cache_key = ResponseCache.make_key('GET', url, headers)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        attempt = 0
        while True:
            try:
                # Check if client is closed and recreate if needed
                if self._client.is_closed:
                    self._recreate_client()

                response = self._client.get(url, headers=headers,
                                            cookies=cookies)
                if cache_key is not None and response.status_code == 200:
                    self._cache.set(cache_key, response)
                return response
            except Exception as exc:
                if attempt >= retries:
                    raise
                # Recreate the client on connection-state errors
                if self._retry_policy.should_recreate_client(exc):
                    self._recreate_client()
                time.sleep(self._retry_policy.backoff_delay(
                    backoff_seconds, attempt))
                attempt += 1

    def _recreate_client(self) -> None:
        """Recreate the HTTP client when it has been closed."""
        try:
            self._client.close()
        except Exception:
            pass  # Client might already be closed

        # Recreate with same configuration
        self._client, self._verify = self._new_client(self._verify)

    def close(self) -> None:
        self._client.close()
