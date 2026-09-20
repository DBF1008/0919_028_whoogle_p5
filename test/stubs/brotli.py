"""brotli stub backed by zlib; round-trip compatible (offline testing only)."""

import zlib


class error(Exception):
    pass


Error = error


def compress(data, *args, **kwargs):
    return zlib.compress(data)


def decompress(data, *args, **kwargs):
    return zlib.decompress(data)
