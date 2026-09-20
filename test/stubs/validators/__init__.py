"""Minimal offline stub of the `validators` package (domain only)."""

import re

_DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+'
    r'[a-zA-Z]{2,}$')


def domain(value):
    """Return True if value looks like a valid domain name."""
    if not value or len(value) > 253:
        return False
    return bool(_DOMAIN_RE.match(value))
