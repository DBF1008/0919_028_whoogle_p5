import time

import pytest
from stem import Signal, SocketError

import app.request as request_module
import app.services.connection_manager as cm_module
from app.services import provider
from app.services.connection_manager import (
    ConnectionManager,
    get_connection_manager,
    reset_connection_manager,
)
from app.services.http_client import HttpxClient


class FakeConnection:
    """Minimal stand-in for a managed connection (e.g. Tor Controller)."""

    def __init__(self, healthy=True, fail_on_signal=False):
        self.closed = False
        self.close_calls = 0
        self.signals = []
        self._healthy = healthy
        self._fail_on_signal = fail_on_signal

    def is_alive(self):
        return self._healthy and not self.closed

    def signal(self, signal):
        if self._fail_on_signal:
            raise SocketError('connection lost')
        self.signals.append(signal)

    def close(self):
        self.closed = True
        self.close_calls += 1


@pytest.fixture(autouse=True)
def fresh_manager():
    reset_connection_manager()
    yield
    reset_connection_manager()


@pytest.fixture
def no_http2(monkeypatch):
    # The test environment has no h2 package; force HTTP/1.1 clients
    monkeypatch.setenv('WHOOGLE_DISABLE_HTTP2', '1')
    monkeypatch.setenv('WHOOGLE_HTTP2', '0')


# -- pooling -----------------------------------------------------------

def test_get_or_create_reuses_connection_per_key():
    manager = ConnectionManager()
    created = []

    def factory():
        conn = FakeConnection()
        created.append(conn)
        return conn

    first = manager.get_or_create(('kind', 'a'), factory)
    second = manager.get_or_create(('kind', 'a'), factory)

    assert first is second
    assert len(created) == 1
    assert len(manager) == 1


def test_get_or_create_recreates_unhealthy_connection():
    manager = ConnectionManager()
    holder = []

    def factory():
        # First created connection is unhealthy, the replacement is fine
        conn = FakeConnection(healthy=bool(holder))
        holder.append(conn)
        return conn

    broken = manager.get_or_create(('kind', 'a'), factory,
                                   health_fn=lambda c: c.is_alive())
    healthy = manager.get_or_create(('kind', 'a'), factory,
                                    health_fn=lambda c: c.is_alive())

    assert healthy is not broken
    assert broken.close_calls == 1
    assert len(manager) == 1


# -- health checks -------------------------------------------------------

def test_health_check_drops_unhealthy_connections():
    manager = ConnectionManager()
    manager.get_or_create(('k', 'good'), FakeConnection,
                                 health_fn=lambda c: c.is_alive())
    bad = manager.get_or_create(('k', 'bad'),
                                lambda: FakeConnection(healthy=False),
                                health_fn=lambda c: c.is_alive())

    report = manager.health_check()

    assert report == {('k', 'good'): True, ('k', 'bad'): False}
    assert bad.close_calls == 1
    assert manager.keys() == (('k', 'good'),)


# -- idle eviction -------------------------------------------------------

def test_evict_idle_removes_stale_connections():
    manager = ConnectionManager(max_idle_seconds=60)
    stale = manager.get_or_create(('k', 'stale'), FakeConnection)
    manager.get_or_create(('k', 'fresh'), FakeConnection)

    # Backdate the stale connection beyond the idle limit
    manager._connections[('k', 'stale')].last_used = time.monotonic() - 120

    evicted = manager.evict_idle()

    assert evicted == 1
    assert stale.close_calls == 1
    assert manager.keys() == (('k', 'fresh'),)


def test_evict_idle_with_explicit_zero_limit_evicts_everything():
    manager = ConnectionManager(max_idle_seconds=3600)
    manager.get_or_create(('k', 'a'), FakeConnection)
    manager.get_or_create(('k', 'b'), FakeConnection)

    assert manager.evict_idle(max_idle_seconds=0) == 2
    assert len(manager) == 0


# -- graceful shutdown ---------------------------------------------------

def test_close_all_shuts_down_everything_and_manager_recovers():
    manager = ConnectionManager()
    conns = [manager.get_or_create(('k', str(i)), FakeConnection)
             for i in range(3)]

    manager.close_all()

    assert all(c.close_calls == 1 for c in conns)
    assert len(manager) == 0

    # Manager remains usable after a graceful shutdown
    new_conn = manager.get_or_create(('k', '0'), FakeConnection)
    assert new_conn is not conns[0]
    assert len(manager) == 1


def test_shutdown_alias_calls_close_all():
    manager = ConnectionManager()
    conn = manager.get_or_create(('k', 'a'), FakeConnection)
    manager.shutdown()
    assert conn.close_calls == 1
    assert len(manager) == 0


# -- HTTP client pooling -------------------------------------------------

def test_http_clients_pooled_per_proxy_config(no_http2):
    manager = ConnectionManager()
    # Plain HTTP proxy: the test env has no socksio package installed
    proxies = {'http': 'http://127.0.0.1:8080',
               'https': 'http://127.0.0.1:8080'}

    direct_a = manager.get_http_client({})
    direct_b = manager.get_http_client(None)
    tor = manager.get_http_client(proxies)

    assert direct_a is direct_b
    assert direct_a is not tor
    assert isinstance(tor, HttpxClient)
    assert len(manager) == 2

    manager.close_all()
    assert direct_a.is_closed
    assert tor.is_closed


def test_http_client_health_fn_detects_closed_client(no_http2):
    manager = ConnectionManager()
    client = manager.get_http_client({})
    client.close()

    replacement = manager.get_http_client({})

    assert replacement is not client
    assert not replacement.is_closed
    manager.close_all()


def test_provider_facade_delegates_to_shared_manager(no_http2):
    client = provider.get_http_client({})

    assert client is get_connection_manager().get_http_client({})
    assert len(get_connection_manager()) == 1

    provider.close_all_clients()
    assert client.is_closed
    assert len(get_connection_manager()) == 0


# -- Tor controller pooling ------------------------------------------------

def test_tor_controller_is_pooled(monkeypatch):
    created = []

    def fake_factory():
        conn = FakeConnection()
        created.append(conn)
        return conn

    monkeypatch.setattr(cm_module, 'create_tor_controller', fake_factory)
    manager = ConnectionManager()

    first = manager.get_tor_controller()
    second = manager.get_tor_controller()

    assert first is second
    assert len(created) == 1


def test_send_tor_signal_uses_pooled_controller(monkeypatch):
    fake = FakeConnection()
    monkeypatch.setattr(cm_module, 'create_tor_controller', lambda: fake)
    manager = ConnectionManager()
    monkeypatch.setattr(request_module, 'get_connection_manager',
                        lambda: manager)

    assert request_module.send_tor_signal(Signal.HEARTBEAT) is True
    assert request_module.send_tor_signal(Signal.NEWNYM) is True

    # One pooled controller received both signals (no ad-hoc connections)
    assert fake.signals == [Signal.HEARTBEAT, Signal.NEWNYM]
    assert len(manager) == 1
    assert request_module.os.environ['TOR_AVAILABLE'] == '1'


def test_send_tor_signal_evicts_broken_controller(monkeypatch):
    broken = FakeConnection(fail_on_signal=True)
    monkeypatch.setattr(cm_module, 'create_tor_controller', lambda: broken)
    manager = ConnectionManager()
    monkeypatch.setattr(request_module, 'get_connection_manager',
                        lambda: manager)

    assert request_module.send_tor_signal(Signal.HEARTBEAT) is False

    # Broken controller was evicted and closed; next call would reconnect
    assert broken.close_calls == 1
    assert len(manager) == 0
    assert request_module.os.environ['TOR_AVAILABLE'] == '0'
