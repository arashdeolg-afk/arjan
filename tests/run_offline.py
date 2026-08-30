"""Run the test suite with outbound network access blocked.

The suite claims never to touch the network. This proves it rather than
trusting it: any attempt to resolve or connect to a non-loopback address
raises, so a test that quietly starts depending on a vendor being up fails
here instead of becoming an intermittent mystery months later.

Loopback stays open because the web tests bind a local server.

    python3 tests/run_offline.py
"""

from __future__ import annotations

import os
import socket
import sys
import unittest

LOOPBACK = {"127.0.0.1", "::1", "localhost", "", None}

_real_getaddrinfo = socket.getaddrinfo
_real_create_connection = socket.create_connection


class NetworkAccessDenied(RuntimeError):
    """Raised when a test reaches for something outside loopback."""


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host not in LOOPBACK:
        raise NetworkAccessDenied(
            f"a test tried to resolve {host!r}. Tests must not touch the "
            f"network — use the synthetic feed or a recorded fixture.")
    return _real_getaddrinfo(host, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if host not in LOOPBACK:
        raise NetworkAccessDenied(
            f"a test tried to connect to {host!r}. Tests must not touch the "
            f"network — use the synthetic feed or a recorded fixture.")
    return _real_create_connection(address, *args, **kwargs)


def main() -> int:
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.create_connection = _guarded_create_connection

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "src"))

    suite = unittest.defaultTestLoader.discover(start_dir=here)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
