"""Configuration — read from the environment, never from the repo.

Two different things get called "credentials" around Polymarket, and only
one of them is secret:

* **Your address** (0x…40 hex) is public. It is on-chain; anyone can look
  up its positions. Keeping it in an env var is about convenience, not
  secrecy.
* **CLOB API credentials** (a UUID key, a base64 secret, a passphrase) are
  secret. They authenticate L2 requests — order placement and private
  history. Nothing in this read-only package needs them; support exists
  so that a future signing layer has one obvious place to look, and so
  that nobody is tempted to paste them into a source file.

Nothing here writes to disk. If a secret ever appears in a file in this
repo, that is a bug, not a feature.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_address(value: str) -> bool:
    return bool(ADDRESS_RE.match(value.strip()))


def address() -> str | None:
    """The account to inspect by default. `export POLYMKT_ADDRESS=0x…`"""
    value = (os.environ.get("POLYMKT_ADDRESS") or "").strip()
    return value if value and is_address(value) else None


@dataclass(frozen=True)
class ApiCredentials:
    """L2 CLOB credentials. Present or absent — never partially trusted."""

    key: str
    secret: str
    passphrase: str

    def masked(self) -> str:
        return f"{self.key[:8]}…{self.key[-4:]}"


def api_credentials() -> ApiCredentials | None:
    key = (os.environ.get("POLYMKT_API_KEY") or "").strip()
    secret = (os.environ.get("POLYMKT_API_SECRET") or "").strip()
    passphrase = (os.environ.get("POLYMKT_API_PASSPHRASE") or "").strip()
    if key and secret and passphrase:
        return ApiCredentials(key, secret, passphrase)
    return None


def credential_status() -> str:
    """A one-line summary safe to print. Never returns a secret."""
    creds = api_credentials()
    if creds:
        return f"L2 credentials present ({creds.masked()}) — unused by this read-only client"
    partial = [name for name in
               ("POLYMKT_API_KEY", "POLYMKT_API_SECRET", "POLYMKT_API_PASSPHRASE")
               if os.environ.get(name)]
    if partial:
        return (f"incomplete L2 credentials: {', '.join(partial)} set, "
                f"the rest missing — treated as absent")
    return "no L2 credentials set (not needed: everything here is public and read-only)"
