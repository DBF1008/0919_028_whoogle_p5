"""Backwards-compatible facade over the shared ConnectionManager.

This module used to keep a module-level ``_clients`` dict as a global
connection pool without any lifecycle management. Pooling, health
checks, idle eviction and graceful shutdown now live in
app.services.connection_manager; these helpers are kept so existing
imports (app.request, app/__init__) keep working unchanged.
"""

from typing import Dict

from app.services.connection_manager import get_connection_manager
from app.services.http_client import HttpxClient


def get_http_client(proxies: Dict[str, str]) -> HttpxClient:
    """Return the pooled HttpxClient for the given proxy config."""
    return get_connection_manager().get_http_client(proxies)


def close_all_clients() -> None:
    """Gracefully close every pooled connection."""
    get_connection_manager().close_all()
