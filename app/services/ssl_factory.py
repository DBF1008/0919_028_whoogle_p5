"""SSL verification policy and httpx.Client construction.

Extracted from HttpxClient so that SSL concerns (CA bundle selection,
verification toggles, trust-store and insecure fallbacks) live in one
place instead of being embedded in the HTTP client itself.
"""

import os
import ssl
from typing import Any, Dict, Optional, Tuple

import httpx

_TRUE_VALUES = ('1', 'true', 't', 'yes', 'y')


def determine_verify_setting() -> Any:
    """Determine SSL verification setting from environment.

    Honors:
    - WHOOGLE_CA_BUNDLE: path to CA bundle file
    - WHOOGLE_SSL_VERIFY: '0' to disable verification
    - WHOOGLE_SSL_BACKEND: 'system' to prefer system trust store
    """
    ca_bundle = os.environ.get('WHOOGLE_CA_BUNDLE', '').strip()
    if ca_bundle:
        return ca_bundle

    verify_env = os.environ.get('WHOOGLE_SSL_VERIFY', '1').lower()
    if verify_env in ('0', 'false', 'no', 'n'):
        return False

    backend = os.environ.get('WHOOGLE_SSL_BACKEND', '').lower()
    if backend == 'system':
        return ssl.create_default_context()

    return True


def build_httpx_client(proxies: Optional[Dict[str, str]],
                       verify: Any,
                       **client_kwargs: Any) -> httpx.Client:
    """Construct an httpx.Client with proxies and the given verify setting.

    Prefers the modern ``proxy=`` argument, then ``proxies=``, and falls
    back to per-scheme mounts on httpx versions that reject both.
    """
    kwargs = dict(client_kwargs)
    kwargs['verify'] = verify
    proxies = proxies or {}

    if proxies:
        proxy_values = list(proxies.values())
        single_proxy = (
            proxy_values[0]
            if proxy_values and all(v == proxy_values[0] for v in proxy_values)
            else None
        )
        if single_proxy:
            try:
                return httpx.Client(proxy=single_proxy, **kwargs)
            except TypeError:
                pass
        try:
            return httpx.Client(proxies=proxies, **kwargs)
        except TypeError:
            mounts: Dict[str, httpx.Proxy] = {}
            for scheme_key, url in proxies.items():
                mounts[f'{scheme_key}://'] = httpx.Proxy(url)
            return httpx.Client(mounts=mounts, **kwargs)

    return httpx.Client(**kwargs)


def create_client_with_ssl_fallback(
        proxies: Optional[Dict[str, str]],
        verify: Any,
        **client_kwargs: Any) -> Tuple[httpx.Client, Any]:
    """Build an httpx.Client, degrading the SSL config on SSLError.

    Falls back to the system trust store, then (only when explicitly
    allowed via WHOOGLE_INSECURE_FALLBACK) to disabled verification.

    Returns:
        Tuple of (client, verify_setting_actually_used).
    """
    try:
        return build_httpx_client(proxies, verify, **client_kwargs), verify
    except ssl.SSLError:
        try:
            system_ctx = ssl.create_default_context()
            return (build_httpx_client(proxies, system_ctx, **client_kwargs),
                    system_ctx)
        except ssl.SSLError:
            insecure_fallback = os.environ.get(
                'WHOOGLE_INSECURE_FALLBACK', '0').lower() in _TRUE_VALUES
            if insecure_fallback:
                return build_httpx_client(proxies, False, **client_kwargs), False
            raise
