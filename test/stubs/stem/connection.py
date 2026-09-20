"""stem.connection stub (offline testing only)."""


class AuthenticationFailure(Exception):
    pass


def authenticate_cookie(controller, cookie_path=None, **kwargs):
    controller.authenticated = True


def authenticate_password(controller, password=None, **kwargs):
    controller.authenticated = True
