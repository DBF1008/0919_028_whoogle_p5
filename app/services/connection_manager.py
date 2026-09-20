"""Unified lifecycle management for all outbound connections.

This module provides :class:`ConnectionManager`, a single registry that owns
every external connection the application makes:

* pooled :class:`~app.services.http_client.HttpxClient` instances (keyed by
  proxy configuration / HTTP version), and
* pooled Tor control ``Controller`` connections (keyed by control port).

Responsibilities:

* **health checks** -- every connection is validated before it is handed out
  and unhealthy entries are transparently rebuilt;
* **idle eviction** -- connections unused for longer than
  ``max_idle_seconds`` are closed and removed (lazily on access and via an
  optional background reaper thread);
* **graceful shutdown** -- :meth:`ConnectionManager.close_all` closes every
  managed connection exactly once and is safe to call repeatedly.

A process-wide singleton is exposed through :func:`get_connection_manager`.
"""

import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from app.services.http_client import HttpxClient


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class ManagedConnection:
    """Wraps a pooled resource with liveness tracking and health checks."""

    def __init__(self,
                 resource: Any,
                 close_fn: Callable[[Any], None],
                 health_fn: Optional[Callable[[Any], bool]] = None) -> None:
        self.resource = resource
        self._close_fn = close_fn
        self._health_fn = health_fn
        self.last_used = time.monotonic()
        self._closed = False
        self._lock = threading.Lock()

    def is_healthy(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._health_fn is None:
                return True
            try:
                return bool(self._health_fn(self.resource))
            except Exception:
                return False

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def idle_for(self, now: Optional[float] = None) -> float:
        return (now if now is not None else time.monotonic()) - self.last_used

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._close_fn(self.resource)
        except Exception:
            pass


class ConnectionManager:
    """Owns the lifecycle of every outbound connection (HTTP + Tor)."""

    def __init__(self,
                 max_idle_seconds: Optional[int] = None,
                 eviction_interval: Optional[int] = None,
                 autostart_reaper: bool = True) -> None:
        self._max_idle_seconds = (max_idle_seconds if max_idle_seconds is not None
                                  else _env_int('WHOOGLE_CONN_MAX_IDLE', 300))
        self._eviction_interval = (eviction_interval if eviction_interval is not None
                                   else _env_int('WHOOGLE_CONN_EVICT_INTERVAL', 60))
        self._http_clients: Dict[Tuple, ManagedConnection] = {}
        self._tor_controllers: Dict[Tuple, ManagedConnection] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._reaper_thread: Optional[threading.Thread] = None
        if autostart_reaper and self._eviction_interval > 0:
            self._start_reaper()

    # ------------------------------------------------------------------
    # HTTP client pool
    # ------------------------------------------------------------------
    @staticmethod
    def _http_key(proxies: Optional[Dict[str, str]], http2: bool) -> Tuple:
        items = tuple(sorted((proxies or {}).items()))
        return ('http', items, bool(http2))

    def get_http_client(self,
                        proxies: Optional[Dict[str, str]] = None,
                        http2: bool = True) -> HttpxClient:
        """Return a healthy pooled HTTP client for the given configuration."""
        key = self._http_key(proxies, http2)
        with self._lock:
            if self._closed:
                raise RuntimeError('ConnectionManager has been shut down')
            entry = self._http_clients.get(key)
            if entry is not None and entry.is_healthy():
                entry.touch()
                return entry.resource
            if entry is not None:
                entry.close()
                del self._http_clients[key]
            client = HttpxClient(proxies=proxies or None, http2=http2)
            self._http_clients[key] = ManagedConnection(
                client,
                close_fn=lambda c: c.close(),
                health_fn=lambda c: not c.is_closed)
            return client

    # ------------------------------------------------------------------
    # Tor controller pool
    # ------------------------------------------------------------------
    @staticmethod
    def _tor_key(host: str, port: int) -> Tuple:
        return ('tor', host, int(port))

    def get_tor_controller(self,
                           factory: Callable[[], Any],
                           host: str = '127.0.0.1',
                           port: int = 9051) -> Any:
        """Return a healthy pooled Tor control connection.

        ``factory`` is invoked to build (and authenticate) a new controller
        when the pool has no healthy entry. It must return an object exposing
        stem's ``Controller`` interface (``signal``/``is_alive``/``close``).
        """
        key = self._tor_key(host, port)
        with self._lock:
            if self._closed:
                raise RuntimeError('ConnectionManager has been shut down')
            entry = self._tor_controllers.get(key)
            if entry is not None and entry.is_healthy():
                entry.touch()
                return entry.resource
            if entry is not None:
                entry.close()
                del self._tor_controllers[key]
            controller = factory()
            self._tor_controllers[key] = ManagedConnection(
                controller,
                close_fn=lambda c: c.close(),
                health_fn=lambda c: c.is_alive())
            return controller

    def evict_tor_controller(self, host: str = '127.0.0.1', port: int = 9051) -> None:
        """Drop a Tor controller from the pool (e.g. after a failure)."""
        key = self._tor_key(host, port)
        with self._lock:
            entry = self._tor_controllers.pop(key, None)
        if entry is not None:
            entry.close()

    # ------------------------------------------------------------------
    # Health checks / idle eviction
    # ------------------------------------------------------------------
    def _pools(self):
        return (self._http_clients, self._tor_controllers)

    def health_check(self) -> Dict[str, int]:
        """Snapshot of pool health: total vs healthy connection counts."""
        with self._lock:
            entries = [e for pool in self._pools() for e in pool.values()]
        healthy = sum(1 for e in entries if e.is_healthy())
        return {'total': len(entries), 'healthy': healthy,
                'unhealthy': len(entries) - healthy}

    def evict_idle(self, now: Optional[float] = None) -> int:
        """Close and remove connections idle longer than the configured TTL."""
        if self._max_idle_seconds <= 0:
            return 0
        now = now if now is not None else time.monotonic()
        evicted = []
        with self._lock:
            for pool in self._pools():
                for key, entry in list(pool.items()):
                    if entry.idle_for(now) > self._max_idle_seconds:
                        evicted.append(entry)
                        del pool[key]
        for entry in evicted:
            entry.close()
        return len(evicted)

    def _start_reaper(self) -> None:
        def _reap():
            while True:
                time.sleep(self._eviction_interval)
                with self._lock:
                    if self._closed:
                        return
                try:
                    self.evict_idle()
                except Exception:
                    pass

        self._reaper_thread = threading.Thread(
            target=_reap, name='connection-manager-reaper', daemon=True)
        self._reaper_thread.start()

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    def close_all(self) -> None:
        """Close every managed connection. Idempotent and thread-safe."""
        with self._lock:
            entries = [e for pool in self._pools() for e in pool.values()]
            for pool in self._pools():
                pool.clear()
        for entry in entries:
            entry.close()

    def shutdown(self) -> None:
        """Gracefully stop the reaper and close all connections."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.close_all()
        thread = self._reaper_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


_manager: Optional[ConnectionManager] = None
_manager_lock = threading.Lock()


def get_connection_manager() -> ConnectionManager:
    """Return the process-wide :class:`ConnectionManager` singleton."""
    global _manager
    with _manager_lock:
        if _manager is None or _manager._closed:
            _manager = ConnectionManager()
        return _manager


def reset_connection_manager() -> None:
    """Shut down and discard the singleton (primarily for tests)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.shutdown()
        _manager = None
