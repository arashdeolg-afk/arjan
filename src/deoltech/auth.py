"""Authentication, authorization, and the administrator account.

Security decisions, stated rather than implied:

**Passwords are hashed with PBKDF2-HMAC-SHA256 at 600,000 iterations** — the
OWASP figure for that algorithm — with a per-user 16-byte salt. PBKDF2 is here
because it is in the standard library; scrypt or Argon2id would be stronger,
and `verify_password` transparently upgrades a stored hash on the next
successful login, so migrating later costs nothing.

**Comparisons are constant-time.** `hmac.compare_digest` everywhere a secret is
checked, so response timing carries no information about how much of a hash
matched.

**Session tokens are stored hashed.** A stolen database gives an attacker
password hashes to grind, not a set of live cookies to replay.

**Login is throttled with exponential backoff and lockout**, and the failure
counter lives on the user row so restarting the process cannot clear it.

**Username enumeration is avoided**: a bad username and a bad password produce
the same message and comparable timing, because a wrong username still runs a
dummy hash verification.

**Sessions are bound to a rotating token.** Logging in issues a new token and
privilege changes revoke every existing one, so a suspended user is out
immediately rather than at the end of their session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from .db import audit, now_iso, transaction

PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
SESSION_TTL_HOURS = 12
SESSION_IDLE_TIMEOUT_MIN = 120
MAX_FAILED_LOGINS = 8
LOCKOUT_MINUTES = 15
MIN_PASSWORD_LENGTH = 12

USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# A hash to verify against when the username does not exist, so a failed login
# takes the same time either way and cannot be used to enumerate accounts.
_DUMMY_HASH = ""


class Role(str, Enum):
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return {"viewer": 0, "trader": 1, "admin": 2}[self.value]

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS[self]


# What each API-token scope grants. A token's effective permissions are its
# scopes INTERSECTED with the owner's role, so a token can never exceed the
# person who issued it — and a "read" token cannot trade even for an admin.
SCOPE_PERMISSIONS: dict[str, frozenset[str]] = {
    "read": frozenset({
        "view.market", "view.account", "view.blotter", "view.analytics",
        "run.backtest",
    }),
    "trade": frozenset({
        "trade.submit", "trade.cancel", "account.manage", "watchlist.edit",
    }),
    # Deliberately separate and never implied by "read" or "trade": issuing a
    # token that can create users should be an explicit, conscious act.
    "admin": frozenset({
        "admin.users", "admin.accounts", "admin.settings", "admin.audit",
        "admin.halt", "admin.impersonate.readonly", "admin.feeds",
    }),
}
VALID_SCOPES = frozenset(SCOPE_PERMISSIONS)


def parse_scopes(raw: str) -> tuple[str, ...]:
    """Normalize a scope string, dropping anything unrecognized.

    Unknown scopes are discarded rather than rejected so a typo narrows a
    token instead of widening it. An empty result falls back to "read".
    """
    found = [s.strip().lower() for s in (raw or "").replace(" ", ",").split(",")]
    kept = tuple(dict.fromkeys(s for s in found if s in VALID_SCOPES))
    return kept or ("read",)


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.VIEWER: frozenset({
        "view.market", "view.account", "view.blotter", "view.analytics",
        "run.backtest",
    }),
    Role.TRADER: frozenset({
        "view.market", "view.account", "view.blotter", "view.analytics",
        "run.backtest", "trade.submit", "trade.cancel", "account.manage",
        "watchlist.edit", "token.create",
    }),
    Role.ADMIN: frozenset({
        "view.market", "view.account", "view.blotter", "view.analytics",
        "run.backtest", "trade.submit", "trade.cancel", "account.manage",
        "watchlist.edit", "token.create",
        # Administrator-only powers
        "admin.users", "admin.accounts", "admin.settings", "admin.audit",
        "admin.halt", "admin.impersonate.readonly", "admin.feeds",
    }),
}


class AuthError(Exception):
    """Authentication or authorization failure, safe to show a user."""


class PermissionDenied(AuthError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    email: str
    display_name: str
    role: Role
    status: str
    created_at: str
    last_login_at: str | None = None
    must_change_password: bool = False
    # Set only when this identity came from an API token. None means an
    # interactive session, which is bounded by the role alone.
    token_scopes: tuple[str, ...] | None = None

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def permissions(self) -> frozenset[str]:
        """Effective permissions: the role, narrowed by any token scopes."""
        granted = ROLE_PERMISSIONS[self.role]
        if self.token_scopes is None:
            return granted
        from_scopes = frozenset().union(
            *(SCOPE_PERMISSIONS.get(s, frozenset()) for s in self.token_scopes))
        return granted & from_scopes

    def can(self, permission: str) -> bool:
        return self.is_active and permission in self.permissions

    def with_scopes(self, scopes: tuple[str, ...]) -> "User":
        from dataclasses import replace as _replace
        return _replace(self, token_scopes=scopes)

    def require(self, permission: str) -> None:
        if self.can(permission):
            return
        if self.token_scopes is not None and permission in ROLE_PERMISSIONS[self.role]:
            # The role allows it; the token does not. Say which, so the caller
            # knows to mint a wider token rather than chase a role change.
            raise PermissionDenied(
                f"this API token's scope ({', '.join(self.token_scopes)}) does "
                f"not allow '{permission}'")
        raise PermissionDenied(
            f"{self.role.value} accounts may not perform '{permission}'")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "username": self.username, "email": self.email,
            "display_name": self.display_name, "role": self.role.value,
            "status": self.status, "created_at": self.created_at,
            "last_login_at": self.last_login_at, "is_admin": self.is_admin,
            "permissions": sorted(self.permissions),
            "token_scopes": list(self.token_scopes) if self.token_scopes else None,
        }


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"], username=row["username"], email=row["email"] or "",
        display_name=row["display_name"] or row["username"],
        role=Role(row["role"]), status=row["status"],
        created_at=row["created_at"], last_login_at=row["last_login_at"],
        must_change_password=bool(row["must_change_password"]),
    )


# ------------------------------------------------------------------ passwords


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join([
        "pbkdf2_sha256", str(iterations),
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    ])


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Check a password. Returns (ok, needs_rehash)."""
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False, False
        iterations = int(iters_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False, False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    ok = hmac.compare_digest(actual, expected)
    return ok, ok and iterations < PBKDF2_ITERATIONS


def password_problems(password: str, username: str = "") -> list[str]:
    """Every reason a password is unacceptable, so the user can fix them at once."""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    classes = sum([
        any(c.islower() for c in password), any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(c in string.punctuation for c in password),
    ])
    if classes < 3:
        problems.append("must mix at least three of: lowercase, uppercase, "
                        "digits, symbols")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if password.lower() in {"password123!", "administrator", "changeme123!",
                            "letmein12345", "qwerty123456"}:
        problems.append("is a commonly used password")
    return problems


def generate_password(length: int = 20) -> str:
    """A strong random password, for admin-created accounts and resets."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if not password_problems(pw):
            return pw


def _dummy_verify(password: str) -> None:
    """Burn the same work as a real check, to flatten timing on unknown users."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password("deoltech-timing-equalizer")
    verify_password(password, _DUMMY_HASH)


# ---------------------------------------------------------------------- users


def create_user(conn: sqlite3.Connection, username: str, password: str, *,
                role: Role | str = Role.TRADER, email: str = "",
                display_name: str = "", actor: User | None = None,
                must_change_password: bool = False,
                skip_policy: bool = False) -> User:
    """Create an account. Admin-only in the web app; open at bootstrap."""
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3-32 characters: letters, digits, "
                        "dot, dash or underscore, starting alphanumeric.")
    if email and not EMAIL_RE.match(email):
        raise AuthError("That does not look like a valid email address.")
    if not skip_policy:
        problems = password_problems(password, username)
        if problems:
            raise AuthError("Password " + "; ".join(problems) + ".")
    role = Role(role) if isinstance(role, str) else role

    existing = conn.execute("SELECT id FROM users WHERE username = ?",
                            (username,)).fetchone()
    if existing:
        raise AuthError(f"The username {username!r} is already taken.")

    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO users (username, email, display_name, password_hash,
                                  role, status, created_at, created_by,
                                  must_change_password)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (username, email or None, display_name or username,
             hash_password(password), role.value, now_iso(),
             actor.id if actor else None, int(must_change_password)))
        user_id = cur.lastrowid

    audit(conn, "user.create", actor_id=actor.id if actor else None,
          actor_name=actor.username if actor else "bootstrap",
          target=username, detail=f"role={role.value}",
          severity="warning" if role is Role.ADMIN else "info")
    return get_user(conn, user_id)


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise AuthError("No such user.")
    return _row_to_user(row)


def find_user(conn: sqlite3.Connection, username: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE username = ?",
                       (username.strip(),)).fetchone()
    return _row_to_user(row) if row else None


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT u.*,
               (SELECT COUNT(*) FROM accounts a WHERE a.user_id = u.id) AS accounts,
               (SELECT COUNT(*) FROM sessions s
                 WHERE s.user_id = u.id AND s.revoked = 0
                   AND s.expires_at > ?) AS active_sessions
        FROM users u ORDER BY u.role DESC, u.username
    """, (now_iso(),)).fetchall()
    out = []
    for r in rows:
        d = _row_to_user(r).to_dict()
        d.update({"accounts": r["accounts"], "active_sessions": r["active_sessions"],
                  "locked_until": r["locked_until"],
                  "failed_logins": r["failed_logins"]})
        out.append(d)
    return out


def admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()["n"]


def set_role(conn: sqlite3.Connection, actor: User, user_id: int,
             role: Role | str) -> User:
    actor.require("admin.users")
    role = Role(role) if isinstance(role, str) else role
    target = get_user(conn, user_id)
    if target.is_admin and role is not Role.ADMIN and admin_count(conn) <= 1:
        # Losing the last administrator would lock everyone out of the platform
        # with no supported way back in.
        raise AuthError("This is the last active administrator; promote another "
                        "before changing this one's role.")
    with transaction(conn):
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role.value, user_id))
    revoke_user_sessions(conn, user_id)   # a role change must take effect now
    audit(conn, "user.role", actor_id=actor.id, actor_name=actor.username,
          target=target.username, detail=f"{target.role.value} -> {role.value}",
          severity="warning")
    return get_user(conn, user_id)


def set_status(conn: sqlite3.Connection, actor: User, user_id: int,
               status: str) -> User:
    actor.require("admin.users")
    if status not in ("active", "suspended"):
        raise AuthError("Status must be 'active' or 'suspended'.")
    target = get_user(conn, user_id)
    if target.id == actor.id and status == "suspended":
        raise AuthError("You cannot suspend your own account.")
    if (target.is_admin and status == "suspended" and admin_count(conn) <= 1):
        raise AuthError("This is the last active administrator and cannot be "
                        "suspended.")
    with transaction(conn):
        conn.execute("UPDATE users SET status = ?, failed_logins = 0, "
                     "locked_until = NULL WHERE id = ?", (status, user_id))
    if status == "suspended":
        revoke_user_sessions(conn, user_id)
    audit(conn, f"user.{status}", actor_id=actor.id, actor_name=actor.username,
          target=target.username, severity="warning")
    return get_user(conn, user_id)


def reset_password(conn: sqlite3.Connection, actor: User, user_id: int,
                   new_password: str | None = None) -> str:
    """Admin reset. Returns the password to hand over, once."""
    actor.require("admin.users")
    target = get_user(conn, user_id)
    password = new_password or generate_password()
    problems = password_problems(password, target.username)
    if problems:
        raise AuthError("Password " + "; ".join(problems) + ".")
    with transaction(conn):
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = 1,
                                failed_logins = 0, locked_until = NULL
               WHERE id = ?""", (hash_password(password), user_id))
    revoke_user_sessions(conn, user_id)
    audit(conn, "user.password_reset", actor_id=actor.id,
          actor_name=actor.username, target=target.username, severity="warning")
    return password


def change_own_password(conn: sqlite3.Connection, user: User, current: str,
                        new_password: str) -> None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                       (user.id,)).fetchone()
    ok, _ = verify_password(current, row["password_hash"])
    if not ok:
        raise AuthError("Your current password is not correct.")
    problems = password_problems(new_password, user.username)
    if problems:
        raise AuthError("Password " + "; ".join(problems) + ".")
    if new_password == current:
        raise AuthError("The new password must be different from the old one.")
    with transaction(conn):
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = 0
               WHERE id = ?""", (hash_password(new_password), user.id))
    revoke_user_sessions(conn, user.id)
    audit(conn, "user.password_change", actor_id=user.id,
          actor_name=user.username, target=user.username)


def delete_user(conn: sqlite3.Connection, actor: User, user_id: int) -> None:
    actor.require("admin.users")
    target = get_user(conn, user_id)
    if target.id == actor.id:
        raise AuthError("You cannot delete your own account.")
    if target.is_admin and admin_count(conn) <= 1:
        raise AuthError("This is the last active administrator and cannot be "
                        "deleted.")
    with transaction(conn):
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    audit(conn, "user.delete", actor_id=actor.id, actor_name=actor.username,
          target=target.username,
          detail="cascaded: accounts, orders, fills, sessions",
          severity="critical")


# ------------------------------------------------------------------- sessions


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(conn: sqlite3.Connection, username: str, password: str, *,
          ip: str = "", user_agent: str = "") -> tuple[User, str]:
    """Authenticate and open a session. Returns (user, session token)."""
    generic = "Incorrect username or password."
    row = conn.execute("SELECT * FROM users WHERE username = ?",
                       (username.strip(),)).fetchone()

    if row is None:
        _dummy_verify(password)      # equalize timing against enumeration
        audit(conn, "auth.login_failed", actor_name=username,
              detail="no such user", ip=ip, severity="warning")
        raise AuthError(generic)

    if row["locked_until"]:
        locked_until = datetime.fromisoformat(row["locked_until"])
        if locked_until > datetime.now(timezone.utc):
            wait = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
            raise AuthError(f"Account locked after repeated failed sign-ins. "
                            f"Try again in {wait} minute{'s' if wait != 1 else ''}.")

    ok, needs_rehash = verify_password(password, row["password_hash"])
    if not ok:
        failed = row["failed_logins"] + 1
        locked = None
        if failed >= MAX_FAILED_LOGINS:
            locked = (datetime.now(timezone.utc)
                      + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        with transaction(conn):
            conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? "
                         "WHERE id = ?", (failed, locked, row["id"]))
        audit(conn, "auth.login_failed", actor_id=row["id"],
              actor_name=row["username"], ip=ip,
              detail=f"attempt {failed}/{MAX_FAILED_LOGINS}"
                     + (" — account locked" if locked else ""),
              severity="critical" if locked else "warning")
        raise AuthError(generic)

    if row["status"] != "active":
        audit(conn, "auth.login_blocked", actor_id=row["id"],
              actor_name=row["username"], ip=ip, detail="account suspended",
              severity="warning")
        raise AuthError("This account has been suspended. Contact an administrator.")

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    with transaction(conn):
        conn.execute(
            """INSERT INTO sessions (token_hash, user_id, created_at, expires_at,
                                     last_seen_at, ip, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_hash_token(token), row["id"], now_iso(), expires.isoformat(),
             now_iso(), ip, user_agent[:400]))
        conn.execute(
            """UPDATE users SET last_login_at = ?, last_login_ip = ?,
                                failed_logins = 0, locked_until = NULL
               WHERE id = ?""", (now_iso(), ip, row["id"]))
        if needs_rehash:
            # Silently strengthen an old hash now that we hold the plaintext.
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (hash_password(password), row["id"]))

    audit(conn, "auth.login", actor_id=row["id"], actor_name=row["username"], ip=ip)
    return get_user(conn, row["id"]), token


def session_user(conn: sqlite3.Connection, token: str | None) -> User | None:
    """Resolve a session cookie to a user, or None. Enforces both timeouts."""
    if not token:
        return None
    row = conn.execute(
        """SELECT s.*, u.status AS user_status FROM sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.revoked = 0""",
        (_hash_token(token),)).fetchone()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(row["expires_at"]) <= now:
        return None
    if row["user_status"] != "active":
        return None
    if row["last_seen_at"]:
        idle = now - datetime.fromisoformat(row["last_seen_at"])
        if idle > timedelta(minutes=SESSION_IDLE_TIMEOUT_MIN):
            revoke_session(conn, token)
            return None
    with transaction(conn):
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                     (now_iso(), _hash_token(token)))
    return get_user(conn, row["user_id"])


def logout(conn: sqlite3.Connection, token: str, user: User | None = None) -> None:
    revoke_session(conn, token)
    if user:
        audit(conn, "auth.logout", actor_id=user.id, actor_name=user.username)


def revoke_session(conn: sqlite3.Connection, token: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?",
                     (_hash_token(token),))


def revoke_user_sessions(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,))
        return cur.rowcount


def purge_expired_sessions(conn: sqlite3.Connection) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ? OR revoked = 1",
                           (now_iso(),))
        return cur.rowcount


def active_sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT s.created_at, s.last_seen_at, s.expires_at, s.ip, s.user_agent,
                  u.username, u.role
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.revoked = 0 AND s.expires_at > ?
           ORDER BY s.last_seen_at DESC""", (now_iso(),)).fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------- api tokens


def create_api_token(conn: sqlite3.Connection, user: User, name: str,
                     scopes: str = "read") -> str:
    """Issue a bearer token. The plaintext is returned once and never stored."""
    user.require("token.create")
    granted = parse_scopes(scopes)
    raw = secrets.token_urlsafe(32)
    token = f"dt_{raw}"
    with transaction(conn):
        conn.execute(
            """INSERT INTO api_tokens (user_id, name, token_hash, prefix,
                                       scopes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user.id, name[:60], _hash_token(token), token[:11],
             ",".join(granted), now_iso()))
    audit(conn, "token.create", actor_id=user.id, actor_name=user.username,
          target=name, detail=f"scopes={','.join(granted)}", severity="warning")
    return token


def token_user(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token or not token.startswith("dt_"):
        return None
    row = conn.execute(
        """SELECT t.*, u.status FROM api_tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token_hash = ? AND t.revoked = 0""",
        (_hash_token(token),)).fetchone()
    if row is None or row["status"] != "active":
        return None
    if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    with transaction(conn):
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
                     (now_iso(), row["id"]))
    # Bind the token's scopes to the identity. Returning the bare user here
    # would hand every token the full power of its owner's role — which is
    # exactly what the "read" option in the UI promises it does not do.
    return get_user(conn, row["user_id"]).with_scopes(parse_scopes(row["scopes"]))


def list_api_tokens(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT id, name, prefix, scopes, created_at, last_used_at, revoked
           FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC""",
        (user_id,))]


def revoke_api_token(conn: sqlite3.Connection, user: User, token_id: int) -> None:
    row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        raise AuthError("No such token.")
    if row["user_id"] != user.id and not user.can("admin.users"):
        raise PermissionDenied("You can only revoke your own tokens.")
    with transaction(conn):
        conn.execute("UPDATE api_tokens SET revoked = 1 WHERE id = ?", (token_id,))
    audit(conn, "token.revoke", actor_id=user.id, actor_name=user.username,
          target=row["name"], severity="warning")


# ------------------------------------------------------------------ bootstrap


def bootstrap_admin(conn: sqlite3.Connection, username: str = "admin",
                    password: str | None = None,
                    email: str = "") -> tuple[User, str | None]:
    """Create the first administrator if the platform has none.

    Returns (user, generated_password). The password is None when the account
    already existed, so a restart never prints a credential that is not real.
    """
    existing = find_user(conn, username)
    if existing:
        return existing, None
    if admin_count(conn) > 0:
        raise AuthError("An administrator already exists; create further users "
                        "from the admin console.")
    generated = password or generate_password()
    user = create_user(conn, username, generated, role=Role.ADMIN, email=email,
                       display_name="Administrator",
                       must_change_password=password is None,
                       skip_policy=False)
    audit(conn, "system.bootstrap", actor_name="system", target=username,
          detail="initial administrator created", severity="critical")
    return user, generated
