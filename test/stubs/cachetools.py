"""Minimal TTLCache stub (offline testing only)."""

import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, maxsize, ttl):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data = OrderedDict()

    def _expired(self, key):
        return time.monotonic() - self._data[key][1] > self.ttl

    def get(self, key, default=None):
        if key not in self._data:
            return default
        if self._expired(key):
            del self._data[key]
            return default
        return self._data[key][0]

    def __setitem__(self, key, value):
        while len(self._data) >= self.maxsize:
            self._data.popitem(last=False)
        self._data[key] = (value, time.monotonic())

    def __contains__(self, key):
        return self.get(key) is not None

    def __len__(self):
        return len(self._data)
