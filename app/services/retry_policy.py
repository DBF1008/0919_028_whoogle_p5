"""Retry policy for outbound HTTP requests.

Extracted from HttpxClient so that retry/backoff decisions and
connection-state error classification live in one testable place.
"""

import httpx

# Import h2 exceptions for better error handling
try:
    from h2.exceptions import ProtocolError as H2ProtocolError
except ImportError:
    H2ProtocolError = None


class RetryPolicy:
    """Classifies request failures and computes backoff delays."""

    @staticmethod
    def should_recreate_client(exc: Exception) -> bool:
        """Return True if the error indicates a broken underlying client.

        Covers closed-client errors and HTTP/2 protocol state errors,
        both of which are unrecoverable without recreating the client.
        """
        if isinstance(exc, (httpx.HTTPError, RuntimeError)):
            if 'client has been closed' in str(exc).lower():
                return True

        # Handle H2 protocol errors (connection state issues)
        if H2ProtocolError and isinstance(exc, H2ProtocolError):
            return True

        # Also check if the error message contains h2 protocol error info
        if 'ProtocolError' in str(exc) or 'ConnectionState.CLOSED' in str(exc):
            return True

        return False

    @staticmethod
    def backoff_delay(backoff_seconds: float, attempt: int) -> float:
        """Exponential backoff delay for the given (0-based) attempt."""
        return backoff_seconds * (2 ** attempt)
