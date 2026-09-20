"""stem stub (offline testing only).

Provides the Signal enum and error types; Controller is in stem.control.
"""

from enum import Enum


class Signal(str, Enum):
    HEARTBEAT = 'HEARTBEAT'
    NEWNYM = 'NEWNYM'
    RELOAD = 'RELOAD'
    HALT = 'HALT'


class SocketError(Exception):
    pass
