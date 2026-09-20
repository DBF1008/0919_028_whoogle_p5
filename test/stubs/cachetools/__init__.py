"""Minimal offline stub of cachetools (TTLCache only)."""

import time
from collections import OrderedDict


class TTLCache:
    """Drop-in subset of cachetools.TTLCache used by whoogle."""

    def __init__(self, maxsize=128, ttl=600):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data = OrderedDict()

    def _expired(self, timestamp):
        return time.monotonic() - timestamp > self.ttl

    def _purge(self):
        for key in [k for k, (_, ts) in self._data.items()
                    if self._expired(ts)]:
            del self._data[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __getitem__(self, key):
        value, timestamp = self._data[key]
        if self._expired(timestamp):
            del self._data[key]
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        self._purge()
        if key in self._data:
            del self._data[key]
        while len(self._data) >= self.maxsize:
            self._data.popitem(last=False)
        self._data[key] = (value, time.monotonic())

    def __delitem__(self, key):
        del self._data[key]

    def __contains__(self, key):
        try:
            self[key]
            return True
        except KeyError:
            return False

    def __len__(self):
        self._purge()
        return len(self._data)

    def clear(self):
        self._data.clear()
