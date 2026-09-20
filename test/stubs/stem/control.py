"""stem.control stub (offline testing only)."""

from stem import SocketError


class Controller:
    def __init__(self, address='127.0.0.1', port=9051):
        self.address = address
        self.port = port
        self.authenticated = False
        self._alive = True
        self.sent_signals = []

    @classmethod
    def from_port(cls, address='127.0.0.1', port=9051):
        # No real Tor instance in the test environment
        raise SocketError('connection refused (stem test stub)')

    def is_alive(self):
        return self._alive

    def signal(self, signal):
        self.sent_signals.append(signal)

    def close(self):
        self._alive = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
