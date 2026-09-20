"""validators stub (offline testing only)."""

import re

_DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+'
    r'[a-zA-Z]{2,}$')


def domain(value, *args, **kwargs):
    return bool(value) and bool(_DOMAIN_RE.match(value))
