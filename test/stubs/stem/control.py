"""Offline stub of stem.control."""

from stem import SocketError


class Controller:
    """Stub Tor controller; from_port always fails to connect."""

    def __init__(self):
        self.signals = []

    @classmethod
    def from_port(cls, address='127.0.0.1', port=9051):
        raise SocketError('connection refused (stem stub)')

    def is_alive(self):
        return True

    def signal(self, signal):
        self.signals.append(signal)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
