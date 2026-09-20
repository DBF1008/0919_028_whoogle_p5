"""Unified lifecycle management for all outbound connections.

ConnectionManager owns every long-lived external connection used by the
app -- pooled HTTP clients and the Tor control connection -- and
provides a single place for:

- pooling: one connection per key, created lazily and reused
- health checks: unhealthy/closed connections are dropped and recreated
- idle eviction: connections unused beyond a TTL are closed and removed
- graceful shutdown: close_all() releases every managed connection

A module-level singleton is exposed via get_connection_manager() so the
Flask app, the request layer and the provider facade all share one pool.
"""

import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from app.services.http_client import HttpxClient

_TRUE_VALUES = ('1', 'true', 't', 'yes', 'y')

# Default idle timeout for pooled connections (seconds)
DEFAULT_MAX_IDLE_SECONDS = 300.0


def _proxies_key(proxies: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    if not proxies:
        return tuple()
    return tuple(sorted(proxies.items()))


def create_tor_controller():
    """Create and authenticate a Tor control connection.

    Imported lazily so that stem is only required when Tor is actually
    used. Raises stem.SocketError/AuthenticationFailure on failure.
    """
    from stem.connection import authenticate_cookie, authenticate_password
    from stem.control import Controller

    from app.utils.misc import read_config_bool

    confloc = './misc/tor/control.conf'
    # Check that the custom location of conf is real.
    temp = os.getenv('WHOOGLE_TOR_CONF', '')
    if os.path.isfile(temp):
        confloc = temp

    controller = Controller.from_port(port=9051)
    if read_config_bool('WHOOGLE_TOR_USE_PASS'):
        with open(confloc, 'r') as conf:
            # Scan for the last line of the file.
            for line in conf:
                pass
            secret = line.strip('\n')
        authenticate_password(controller, password=secret)
    else:
        cookie_path = '/var/lib/tor/control_auth_cookie'
        authenticate_cookie(controller, cookie_path=cookie_path)
    return controller


class ManagedConnection:
    """A pooled connection plus its lifecycle metadata."""

    def __init__(self,
                 connection: Any,
                 close_fn: Optional[Callable[[Any], None]] = None,
                 health_fn: Optional[Callable[[Any], bool]] = None) -> None:
        self.connection = connection
        self.created_at = time.monotonic()
        self.last_used = self.created_at
        self._close_fn = close_fn
        self._health_fn = health_fn

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def is_healthy(self) -> bool:
        if self._health_fn is None:
            return True
        try:
            return bool(self._health_fn(self.connection))
        except Exception:
            return False

    def close(self) -> None:
        try:
            if self._close_fn is not None:
                self._close_fn(self.connection)
            else:
                self.connection.close()
        except Exception:
            pass


class ConnectionManager:
    """Pools and supervises all outbound connections."""

    HTTP_KIND = 'http'
    TOR_KIND = 'tor'
    TOR_CONTROLLER_KEY = (TOR_KIND, 'controller')

    def __init__(self, max_idle_seconds: float = DEFAULT_MAX_IDLE_SECONDS) -> None:
        self._lock = threading.RLock()
        self._connections: Dict[tuple, ManagedConnection] = {}
        self._max_idle_seconds = float(max_idle_seconds)

    # -- pooling ------------------------------------------------------

    def get_or_create(self,
                      key: tuple,
                      factory: Callable[[], Any],
                      close_fn: Optional[Callable[[Any], None]] = None,
                      health_fn: Optional[Callable[[Any], bool]] = None) -> Any:
        """Return the pooled connection for key, creating it if needed.

        Unhealthy pooled connections are closed and recreated.
        """
        with self._lock:
            managed = self._connections.get(key)
            if managed is not None and not managed.is_healthy():
                managed.close()
                managed = None
            if managed is None:
                managed = ManagedConnection(
                    factory(), close_fn=close_fn, health_fn=health_fn)
                self._connections[key] = managed
            managed.touch()
            return managed.connection

    def get_http_client(self, proxies: Optional[Dict[str, str]] = None) -> HttpxClient:
        """Return the pooled HttpxClient for the given proxy config."""
        # Determine HTTP/2 enablement from env (default on)
        http2_env = os.environ.get('WHOOGLE_HTTP2', '1').lower()
        http2_enabled = http2_env in _TRUE_VALUES

        key = (self.HTTP_KIND, _proxies_key(proxies or {}), http2_enabled)
        return self.get_or_create(
            key,
            factory=lambda: HttpxClient(proxies=proxies or None,
                                        http2=http2_enabled),
            health_fn=lambda client: not client.is_closed)

    def get_tor_controller(self):
        """Return the pooled, authenticated Tor control connection."""
        return self.get_or_create(
            self.TOR_CONTROLLER_KEY,
            factory=create_tor_controller,
            health_fn=lambda controller: controller.is_alive())

    # -- lifecycle ----------------------------------------------------

    def health_check(self) -> Dict[tuple, bool]:
        """Check all pooled connections, dropping unhealthy ones.

        Returns:
            Dict mapping each checked key to its health status.
        """
        with self._lock:
            report = {}
            for key, managed in list(self._connections.items()):
                healthy = managed.is_healthy()
                report[key] = healthy
                if not healthy:
                    managed.close()
                    del self._connections[key]
            return report

    def evict_idle(self, max_idle_seconds: Optional[float] = None) -> int:
        """Close and remove connections idle longer than the limit.

        Returns:
            The number of connections evicted.
        """
        idle_limit = float(
            max_idle_seconds if max_idle_seconds is not None
            else self._max_idle_seconds)
        now = time.monotonic()
        evicted = 0
        with self._lock:
            for key, managed in list(self._connections.items()):
                if now - managed.last_used >= idle_limit:
                    managed.close()
                    del self._connections[key]
                    evicted += 1
        return evicted

    def evict(self, key: tuple) -> bool:
        """Close and remove a specific pooled connection, if present."""
        with self._lock:
            managed = self._connections.pop(key, None)
        if managed is None:
            return False
        managed.close()
        return True

    def close_all(self) -> None:
        """Gracefully close every managed connection and clear the pool.

        The manager remains usable afterwards; connections are recreated
        lazily on the next request.
        """
        with self._lock:
            managed_connections = list(self._connections.values())
            self._connections.clear()
        for managed in managed_connections:
            managed.close()

    # Graceful-shutdown alias
    shutdown = close_all

    # -- introspection --------------------------------------------------

    def keys(self) -> Tuple[tuple, ...]:
        with self._lock:
            return tuple(self._connections.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._connections)


_manager: Optional[ConnectionManager] = None
_manager_lock = threading.Lock()


def get_connection_manager() -> ConnectionManager:
    """Return the process-wide shared ConnectionManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ConnectionManager()
    return _manager


def reset_connection_manager() -> None:
    """Shut down and discard the shared manager (mainly for tests)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close_all()
        _manager = None
