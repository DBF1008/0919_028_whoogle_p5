"""Offline stub of stem.connection."""

from stem import SocketError  # noqa: F401


class AuthenticationFailure(Exception):
    """Mirror of stem.connection.AuthenticationFailure."""


def authenticate_cookie(controller, cookie_path=None, **kwargs):
    raise SocketError('authentication unavailable (stem stub)')


def authenticate_password(controller, password=None, **kwargs):
    raise SocketError('authentication unavailable (stem stub)')
