"""HTTP client building blocks.

The module is split into small, single-responsibility units that
:class:`HttpxClient` composes:

* :class:`RetryPolicy` -- retry/backoff behaviour for failed requests;
* :class:`ResponseCache` -- thread-safe TTL caching of responses;
* :func:`resolve_verify_setting` / :func:`build_httpx_client` /
  :func:`create_client_with_ssl_fallback` -- SSL verification resolution and
  ``httpx.Client`` construction with graceful trust-store degradation.

``HttpxClient`` itself stays a thin, reusable wrapper whose public interface
(constructor signature, ``get``/``close``/``proxies``) is unchanged.
"""

import os
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import httpx
from cachetools import TTLCache

# Import h2 exceptions for better error handling
try:
    from h2.exceptions import ProtocolError as H2ProtocolError
except ImportError:
    H2ProtocolError = None


def _env_flag(name: str, default: str = '0') -> bool:
    return os.environ.get(name, default).lower() in ('1', 'true', 't', 'yes', 'y')


# ----------------------------------------------------------------------
# Retry policy
# ----------------------------------------------------------------------
@dataclass
class RetryPolicy:
    """Exponential-backoff retry behaviour for a single request."""

    retries: int = 2
    backoff_seconds: float = 0.5

    def delays(self):
        """Yield the sleep duration before each retry attempt."""
        for attempt in range(self.retries):
            yield self.backoff_seconds * (2 ** attempt)


def should_rebuild_client(exc: Exception) -> bool:
    """Return True if the error indicates the underlying client is broken."""
    if isinstance(exc, (httpx.HTTPError, RuntimeError)):
        if 'client has been closed' in str(exc).lower():
            return True
    # Handle H2 protocol errors (connection state issues)
    if H2ProtocolError and isinstance(exc, H2ProtocolError):
        return True
    # Also check if the error message contains h2 protocol error info
    if 'ProtocolError' in str(exc) or 'ConnectionState.CLOSED' in str(exc):
        return True
    return False


# ----------------------------------------------------------------------
# Response cache
# ----------------------------------------------------------------------
class ResponseCache:
    """Thread-safe TTL cache for successful GET responses."""

    def __init__(self, ttl_seconds: int = 30, maxsize: int = 256) -> None:
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()

    @staticmethod
    def make_key(method: str, url: str,
                 headers: Optional[Dict[str, str]]) -> Tuple:
        normalized_headers = tuple(sorted((headers or {}).items()))
        return (method.upper(), url, normalized_headers)

    def get(self, key: Tuple) -> Optional[httpx.Response]:
        with self._lock:
            return self._cache.get(key)

    def store(self, key: Tuple, response: httpx.Response) -> None:
        if response.status_code == 200:
            with self._lock:
                self._cache[key] = response


# ----------------------------------------------------------------------
# SSL verification / client construction
# ----------------------------------------------------------------------
def resolve_verify_setting() -> Any:
    """Determine SSL verification setting from environment.

    Honors:
    - WHOOGLE_CA_BUNDLE: path to CA bundle file
    - WHOOGLE_SSL_VERIFY: '0' to disable verification
    - WHOOGLE_SSL_BACKEND: 'system' to prefer system trust store
    """
    ca_bundle = os.environ.get('WHOOGLE_CA_BUNDLE', '').strip()
    if ca_bundle:
        return ca_bundle

    if not _env_flag('WHOOGLE_SSL_VERIFY', '1'):
        return False

    if os.environ.get('WHOOGLE_SSL_BACKEND', '').lower() == 'system':
        return ssl.create_default_context()

    return True


def build_httpx_client(proxies: Dict[str, str],
                       verify: Any,
                       **client_kwargs: Any) -> httpx.Client:
    """Construct an ``httpx.Client`` for the given proxy configuration.

    Tries the modern ``proxy=``/``proxies=`` kwargs first and falls back to
    per-scheme ``mounts`` for older httpx versions.
    """
    kwargs = dict(client_kwargs)
    kwargs['verify'] = verify
    if not proxies:
        return httpx.Client(**kwargs)

    proxy_values = list(proxies.values())
    single_proxy = (proxy_values[0]
                    if proxy_values and all(v == proxy_values[0] for v in proxy_values)
                    else None)

    def _mounts_client() -> httpx.Client:
        mounts: Dict[str, httpx.Proxy] = {}
        for scheme_key, url in proxies.items():
            mounts[f'{scheme_key}://'] = httpx.Proxy(url)
        return httpx.Client(mounts=mounts, **kwargs)

    if single_proxy:
        try:
            return httpx.Client(proxy=single_proxy, **kwargs)
        except TypeError:
            try:
                return httpx.Client(proxies=proxies, **kwargs)
            except TypeError:
                return _mounts_client()
    try:
        return httpx.Client(proxies=proxies, **kwargs)
    except TypeError:
        return _mounts_client()


def create_client_with_ssl_fallback(build: Callable[[Any], httpx.Client],
                                    verify: Any) -> Tuple[httpx.Client, Any]:
    """Build a client, degrading the trust store on SSL failures.

    Order of attempts: configured ``verify`` -> system trust store ->
    (optionally, when WHOOGLE_INSECURE_FALLBACK=1) no verification.

    Returns the client and the verify setting that ultimately worked.
    """
    try:
        return build(verify), verify
    except ssl.SSLError:
        pass
    try:
        system_ctx = ssl.create_default_context()
        return build(system_ctx), system_ctx
    except ssl.SSLError:
        if _env_flag('WHOOGLE_INSECURE_FALLBACK'):
            return build(False), False
        raise


# ----------------------------------------------------------------------
# Public client wrapper
# ----------------------------------------------------------------------
class HttpxClient:
    """Thin wrapper around httpx.Client composing retries and TTL caching.

    The client is intended to be safe for reuse across requests. Per-request
    overrides for headers/cookies are supported.
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
        if _env_flag('WHOOGLE_DISABLE_HTTP2'):
            http2 = False

        self._proxies = proxies or {}
        self._http2 = http2
        self._timeout_seconds = timeout_seconds
        self._verify = resolve_verify_setting()
        self._client, self._verify = self._create_client(self._verify)
        self._cache = ResponseCache(ttl_seconds=cache_ttl_seconds,
                                    maxsize=cache_maxsize)

    def _client_kwargs(self) -> Dict[str, Any]:
        return dict(http2=self._http2,
                    timeout=self._timeout_seconds,
                    follow_redirects=True)

    def _create_client(self, verify: Any) -> Tuple[httpx.Client, Any]:
        return create_client_with_ssl_fallback(
            lambda v: build_httpx_client(self._proxies, v, **self._client_kwargs()),
            verify)

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

        policy = RetryPolicy(retries=retries, backoff_seconds=backoff_seconds)
        delays = policy.delays()
        last_exc: Optional[Exception] = None
        attempt = 0
        while attempt <= retries:
            try:
                # Check if client is closed and recreate if needed
                if self._client.is_closed:
                    self._recreate_client()

                response = self._client.get(url, headers=headers, cookies=cookies)
                if use_cache:
                    self._cache.store(cache_key, response)
                return response
            except Exception as exc:
                last_exc = exc
                if should_rebuild_client(exc):
                    self._recreate_client()
                if attempt == retries:
                    raise
                time.sleep(next(delays))
                attempt += 1

        # Should not reach here
        if last_exc:
            raise last_exc
        raise httpx.HTTPError('Unknown HTTP error')

    def _recreate_client(self) -> None:
        """Recreate the HTTP client when it has been closed."""
        try:
            self._client.close()
        except Exception:
            pass  # Client might already be closed
        self._client, self._verify = self._create_client(self._verify)

    def close(self) -> None:
        self._client.close()
