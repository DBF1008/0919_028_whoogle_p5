"""Offline stub of waitress (serving is never exercised in unit tests)."""


def serve(*args, **kwargs):
    raise RuntimeError('waitress stub cannot serve requests')
