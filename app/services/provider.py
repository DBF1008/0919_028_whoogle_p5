"""Accessors for shared outbound connections.

This module is a thin compatibility layer over
:class:`app.services.connection_manager.ConnectionManager`, which owns the
full lifecycle (pooling, health checks, idle eviction, graceful shutdown) of
every HTTP client and Tor controller connection.
"""

import os
from typing import Dict

from app.services.connection_manager import get_connection_manager
from app.services.http_client import HttpxClient


def _http2_enabled() -> bool:
    # Determine HTTP/2 enablement from env (default on)
    http2_env = os.environ.get('WHOOGLE_HTTP2', '1').lower()
    return http2_env in ('1', 'true', 't', 'yes', 'y')


def get_http_client(proxies: Dict[str, str]) -> HttpxClient:
    """Return the shared, health-checked HTTP client for ``proxies``."""
    return get_connection_manager().get_http_client(
        proxies=proxies or None, http2=_http2_enabled())


def close_all_clients() -> None:
    """Gracefully close every managed connection (HTTP + Tor)."""
    get_connection_manager().close_all()
