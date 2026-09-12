"""
Authentication & User Account Management Module.

Stores accounts in Supabase Postgres (table `app_users`) via its REST API
(PostgREST), using the service_role key server-side. This replaced a local
SQLite file specifically because Render's free plan disk is ephemeral - every
redeploy wiped the user table. Passwords are PBKDF2-HMAC-SHA256 salted hashes,
same as before; only the storage backend changed.

Function signatures and return shapes are unchanged from the SQLite version so
engine/api.py needs no changes.
"""

import os
import re
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Tuple, Optional

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_REST_URL = f"{SUPABASE_URL}/rest/v1/app_users" if SUPABASE_URL else ""
_REQUEST_TIMEOUT = 10


def _headers(prefer: Optional[str] = None) -> dict:
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _require_configured() -> Optional[str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return "Account storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing)."
    return None


def init_db() -> None:
    """
    No-op: the app_users table is created once via supabase_app_users_setup.sql,
    not at runtime. Kept only so callers written against the old SQLite version
    don't need to change.
    """
    return None


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes a password with a 16-byte random salt using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return pw_hash, salt


# Local part follows RFC 5322's common atom set, including '+' for plus-addressing
# (a+tag@mail.io), which the Node-side validator already accepts.
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~.-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r"\.[a-zA-Z]{2,}$"
)


def is_valid_email(email: str) -> bool:
    """Structural validation of an email address. Deliverability is checked in the Node layer."""
    if not email:
        return False
    candidate = email.strip()
    if len(candidate) > 254:
        return False
    local, _, _ = candidate.partition("@")
    if not local or len(local) > 64 or ".." in local or local.startswith(".") or local.endswith("."):
        return False
    return bool(_EMAIL_PATTERN.match(candidate))


def _find_user(email: str) -> Optional[dict]:
    """Returns the app_users row for an email, or None if it doesn't exist."""
    resp = requests.get(
        _REST_URL,
        headers=_headers(),
        params={"email": f"eq.{email}", "select": "*", "limit": "1"},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def signup_user(email: str, password: str) -> Tuple[bool, str]:
    """
    Registers a new user.
    Returns: (success: bool, message: str)
    """
    config_error = _require_configured()
    if config_error:
        return False, config_error

    email_clean = email.strip().lower()

    if not is_valid_email(email_clean):
        return False, "Please provide a valid email address (e.g., user@example.com)."

    if len(password) < 6:
        return False, "Password must be at least 6 characters long."

    pw_hash, salt = hash_password(password)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.post(
            _REST_URL,
            headers=_headers(prefer="return=minimal"),
            json={"email": email_clean, "password_hash": pw_hash, "salt": salt, "created_at": created_at},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 409 or (resp.status_code == 400 and "duplicate key" in resp.text.lower()):
            return False, "An account with this email already exists. Please sign in."
        resp.raise_for_status()
        return True, "Account created successfully! You can now log in."
    except requests.RequestException as e:
        return False, f"Registration error: {str(e)}"


# Sentinel stored in password_hash for accounts that authenticate by OTP only.
# login_user refuses these, so no password - however it was obtained - opens them.
PASSWORDLESS = "!"


def ensure_user(email: str) -> Tuple[bool, str]:
    """
    Register an email as a passwordless account, or confirm it already exists.

    Used after OTP verification. These accounts carry no usable password hash: identity
    is proven by controlling the mailbox, so there is nothing for a password check to
    compare against and nothing an attacker can guess.
    """
    config_error = _require_configured()
    if config_error:
        return False, config_error

    email_clean = email.strip().lower()

    if not is_valid_email(email_clean):
        return False, "Please provide a valid email address."

    try:
        resp = requests.post(
            _REST_URL,
            headers=_headers(prefer="return=minimal"),
            json={
                "email": email_clean,
                "password_hash": PASSWORDLESS,
                "salt": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 409 or (resp.status_code == 400 and "duplicate key" in resp.text.lower()):
            return True, "Account already exists."
        resp.raise_for_status()
        return True, "Account created."
    except requests.RequestException as e:
        return False, f"Registration error: {str(e)}"


def login_user(email: str, password: str) -> Tuple[bool, str]:
    """
    Verifies user credentials.
    Returns: (success: bool, message: str)
    """
    config_error = _require_configured()
    if config_error:
        return False, config_error

    email_clean = email.strip().lower()

    if not email_clean or not password:
        return False, "Please enter both email and password."

    try:
        user = _find_user(email_clean)
    except requests.RequestException as e:
        return False, f"Could not verify credentials right now: {str(e)}"

    if not user:
        return False, "No account found with this email. Please check or create a new account."

    stored_hash = user["password_hash"]
    salt = user["salt"]

    if stored_hash == PASSWORDLESS:
        return False, "This account signs in with an email verification code. Request a code instead."

    computed_hash, _ = hash_password(password, salt)

    if secrets.compare_digest(stored_hash, computed_hash):
        return True, "Login successful."
    else:
        return False, "Incorrect password. Please try again."


def get_total_users() -> int:
    """Returns the total number of registered accounts."""
    config_error = _require_configured()
    if config_error:
        return 0

    resp = requests.get(
        _REST_URL,
        headers=_headers(prefer="count=exact"),
        params={"select": "id", "limit": "1"},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    content_range = resp.headers.get("content-range", "")
    # Format is "0-0/42" (or "*/42" for an empty result) - the total is after the slash.
    if "/" in content_range:
        total = content_range.split("/")[-1]
        if total.isdigit():
            return int(total)
    return len(resp.json())
