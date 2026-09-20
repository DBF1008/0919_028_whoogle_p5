"""Minimal offline stub of the `stem` package (Tor control).

Only the names imported by whoogle are provided. The stub Controller
always fails to connect, which the application handles gracefully
(TOR_AVAILABLE=0). Tests that exercise Tor logic monkeypatch the
controller factory.
"""


class Signal:
    HEARTBEAT = 'HEARTBEAT'
    NEWNYM = 'NEWNYM'


class SocketError(Exception):
    """Mirror of stem.SocketError (control connection failure)."""
