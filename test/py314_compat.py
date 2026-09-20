"""Python 3.12+ compatibility shims for the pinned old dependency stack.

Imported at the very top of test/conftest.py (before `from app import app`)
so the pinned Flask 2.0 / Werkzeug 2.0 stack keeps working on modern
interpreters. Every shim is guarded so it only applies when the running
interpreter actually lacks the attribute.
"""

import ast
import pkgutil


def _make_constant_compat(name):
    class _Compat(ast.Constant):
        def __init__(self, value='', **kwargs):
            # Accept the legacy keyword (e.g. ast.Str(s=...))
            if name == 'Str' and 's' in kwargs:
                value = kwargs.pop('s')
            if name == 'Num' and 'n' in kwargs:
                value = kwargs.pop('n')
            kwargs.pop('kind', None)
            super().__init__(value=value)

        @property
        def s(self):
            return self.value

        @property
        def n(self):
            return self.value

    _Compat.__name__ = name
    return _Compat


for _name in ('Str', 'Num', 'Bytes', 'NameConstant', 'Ellipsis'):
    if not hasattr(ast, _name):
        setattr(ast, _name, _make_constant_compat(_name))

# pkgutil.get_loader was removed in Python 3.14; Flask 2.0 still uses it

if not hasattr(pkgutil, 'get_loader'):
    import importlib.util

    def _get_loader(name):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError, AttributeError):
            spec = None
        if spec is None:
            return None
        return spec.loader

    pkgutil.get_loader = _get_loader
