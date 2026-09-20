import time

import pytest
from stem import Signal

from app.services import connection_manager as cm
from app.services.connection_manager import (
    ConnectionManager,
    ManagedConnection,
    get_connection_manager,
    reset_connection_manager,
)


class FakeHttpClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.close_calls = 0

    @property
    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True
        self.close_calls += 1


class FakeTorController:
    def __init__(self):
        self.alive = True
        self.signals = []
        self.close_calls = 0

    def is_alive(self):
        return self.alive

    def signal(self, signal):
        self.signals.append(signal)

    def close(self):
        self.alive = False
        self.close_calls += 1


@pytest.fixture(autouse=True)
def clean_manager():
    reset_connection_manager()
    yield
    reset_connection_manager()


@pytest.fixture
def manager():
    # No background reaper in unit tests; eviction is triggered manually.
    mgr = ConnectionManager(max_idle_seconds=300, eviction_interval=0,
                            autostart_reaper=False)
    yield mgr
    mgr.shutdown()


def patch_http_client(monkeypatch, manager=None):
    created = []

    def fake_factory(**kwargs):
        client = FakeHttpClient(**kwargs)
        created.append(client)
        return client

    target = cm
    monkeypatch.setattr(target, 'HttpxClient', lambda **kw: fake_factory(**kw))
    return created


# --------------------------------------------------------------------
# HTTP client pooling
# --------------------------------------------------------------------
def test_http_clients_are_pooled_by_key(monkeypatch, manager):
    created = patch_http_client(monkeypatch)
    proxies = {'http': 'socks5://127.0.0.1:9050'}

    c1 = manager.get_http_client(proxies=proxies)
    c2 = manager.get_http_client(proxies=dict(proxies))  # equal config
    c3 = manager.get_http_client(proxies=None)

    assert c1 is c2
    assert c1 is not c3
    assert len(created) == 2


def test_unhealthy_http_client_is_rebuilt(monkeypatch, manager):
    created = patch_http_client(monkeypatch)
    client = manager.get_http_client()
    client.closed = True  # simulate a broken connection

    rebuilt = manager.get_http_client()
    assert rebuilt is not client
    assert client.close_calls >= 1
    assert len(created) == 2


# --------------------------------------------------------------------
# Tor controller pooling
# --------------------------------------------------------------------
def test_tor_controller_is_pooled_and_reused(manager):
    controllers = []

    def factory():
        controller = FakeTorController()
        controllers.append(controller)
        return controller

    t1 = manager.get_tor_controller(factory)
    t2 = manager.get_tor_controller(factory)
    assert t1 is t2
    assert len(controllers) == 1


def test_dead_tor_controller_is_rebuilt(manager):
    controllers = []

    def factory():
        controller = FakeTorController()
        controllers.append(controller)
        return controller

    t1 = manager.get_tor_controller(factory)
    t1.alive = False

    t2 = manager.get_tor_controller(factory)
    assert t2 is not t1
    assert t1.close_calls == 1
    assert len(controllers) == 2


def test_evict_tor_controller(manager):
    controller = manager.get_tor_controller(FakeTorController)
    manager.evict_tor_controller()
    assert controller.close_calls == 1

    replacement = manager.get_tor_controller(FakeTorController)
    assert replacement is not controller


# --------------------------------------------------------------------
# Health checks / idle eviction
# --------------------------------------------------------------------
def test_health_check_reports_counts(monkeypatch, manager):
    patch_http_client(monkeypatch)
    client = manager.get_http_client()
    manager.get_tor_controller(FakeTorController)

    assert manager.health_check() == {'total': 2, 'healthy': 2, 'unhealthy': 0}

    client.closed = True
    report = manager.health_check()
    assert report['total'] == 2
    assert report['healthy'] == 1
    assert report['unhealthy'] == 1


def test_idle_connections_are_evicted(monkeypatch, manager):
    patch_http_client(monkeypatch)
    idle_client = manager.get_http_client(proxies={'http': 'a'})
    fresh_client = manager.get_http_client(proxies={'http': 'b'})

    # Backdate one entry beyond the idle TTL
    key = manager._http_key({'http': 'a'}, True)
    manager._http_clients[key].last_used = time.monotonic() - 9999

    evicted = manager.evict_idle()
    assert evicted == 1
    assert idle_client.close_calls == 1
    assert fresh_client.close_calls == 0
    assert manager.get_http_client(proxies={'http': 'b'}) is fresh_client


def test_evict_idle_disabled_when_ttl_nonpositive(monkeypatch):
    patch_http_client(monkeypatch)
    mgr = ConnectionManager(max_idle_seconds=0, eviction_interval=0,
                            autostart_reaper=False)
    try:
        entry_client = mgr.get_http_client()
        key = mgr._http_key(None, True)
        mgr._http_clients[key].last_used = time.monotonic() - 9999
        assert mgr.evict_idle() == 0
        assert mgr.get_http_client() is entry_client
    finally:
        mgr.shutdown()


# --------------------------------------------------------------------
# Graceful shutdown
# --------------------------------------------------------------------
def test_close_all_closes_everything_once(monkeypatch, manager):
    patch_http_client(monkeypatch)
    client = manager.get_http_client()
    controller = manager.get_tor_controller(FakeTorController)

    manager.close_all()
    assert client.close_calls == 1
    assert controller.close_calls == 1
    assert manager.health_check() == {'total': 0, 'healthy': 0, 'unhealthy': 0}

    # Idempotent: second call must not re-close anything
    manager.close_all()
    assert client.close_calls == 1
    assert controller.close_calls == 1


def test_shutdown_is_idempotent_and_blocks_new_clients(manager):
    manager.shutdown()
    manager.shutdown()  # must not raise
    with pytest.raises(RuntimeError):
        manager.get_http_client()


def test_managed_connection_close_is_idempotent():
    calls = []
    entry = ManagedConnection(object(), close_fn=lambda r: calls.append(r))
    entry.close()
    entry.close()
    assert len(calls) == 1
    assert not entry.is_healthy()


def test_singleton_is_shared_and_resettable():
    m1 = get_connection_manager()
    assert get_connection_manager() is m1
    reset_connection_manager()
    m2 = get_connection_manager()
    assert m2 is not m1


# --------------------------------------------------------------------
# request.py integration: send_tor_signal uses the shared pool
# --------------------------------------------------------------------
def test_send_tor_signal_uses_pooled_controller(monkeypatch):
    import app.request as request_mod

    controllers = []

    def fake_factory():
        controller = FakeTorController()
        controllers.append(controller)
        return controller

    monkeypatch.setattr(request_mod, '_create_tor_controller', fake_factory)

    assert request_mod.send_tor_signal(Signal.HEARTBEAT) is True
    assert request_mod.send_tor_signal(Signal.NEWNYM) is True
    # Both signals went through the same pooled controller
    assert len(controllers) == 1
    assert controllers[0].signals == [Signal.HEARTBEAT, Signal.NEWNYM]
    assert request_mod.os.environ['TOR_AVAILABLE'] == '1'


def test_send_tor_signal_failure_evicts_and_reports(monkeypatch):
    import app.request as request_mod
    from stem import SocketError

    attempts = []

    def flaky_factory():
        controller = FakeTorController()
        if not attempts:
            controller.signal = lambda s: (_ for _ in ()).throw(
                SocketError('boom'))
        attempts.append(controller)
        return controller

    monkeypatch.setattr(request_mod, '_create_tor_controller', flaky_factory)

    assert request_mod.send_tor_signal(Signal.HEARTBEAT) is False
    assert request_mod.os.environ['TOR_AVAILABLE'] == '0'
    # The broken controller was evicted, so a retry builds a fresh one
    assert request_mod.send_tor_signal(Signal.HEARTBEAT) is True
    assert len(attempts) == 2


# --------------------------------------------------------------------
# provider.py compatibility layer
# --------------------------------------------------------------------
def test_provider_delegates_to_manager(monkeypatch):
    from app.services import provider

    created = patch_http_client(monkeypatch)
    client = provider.get_http_client({'http': 'socks5://127.0.0.1:9050'})
    assert client is provider.get_http_client({'http': 'socks5://127.0.0.1:9050'})
    assert len(created) == 1

    provider.close_all_clients()
    assert created[0].close_calls == 1
