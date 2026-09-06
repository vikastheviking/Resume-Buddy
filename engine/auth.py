"""
Authentication & User Account Management Module.
Uses SQLite and PBKDF2-HMAC-SHA256 salted hashing for local, persistent, zero-dependency authentication.
"""

import os
import re
import sqlite3
import hashlib
import secrets
from datetime import datetime
from typing import Tuple, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Runtime state lives outside the source tree; override with RESUME_BUDDY_DATA_DIR
# to point at a mounted volume in containerised deployments.
DATA_DIR = os.environ.get("RESUME_BUDDY_DATA_DIR", os.path.join(_REPO_ROOT, "data"))
DB_PATH = os.path.join(DATA_DIR, "users.db")


def get_db_connection() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the users table if it does not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()


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


def is_valid_email(email: str) -> bool:
    """Basic email regex validation."""
    if not email or len(email) > 120:
        return False
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w{2,}$"
    return bool(re.match(pattern, email.strip()))


def signup_user(email: str, password: str) -> Tuple[bool, str]:
    """
    Registers a new user.
    Returns: (success: bool, message: str)
    """
    init_db()
    email_clean = email.strip().lower()

    if not is_valid_email(email_clean):
        return False, "Please provide a valid email address (e.g., user@example.com)."

    if len(password) < 6:
        return False, "Password must be at least 6 characters long."

    pw_hash, salt = hash_password(password)
    created_at = datetime.utcnow().isoformat()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (email, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (email_clean, pw_hash, salt, created_at)
            )
            conn.commit()
        return True, "Account created successfully! You can now log in."
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists. Please sign in."
    except Exception as e:
        return False, f"Registration error: {str(e)}"


def login_user(email: str, password: str) -> Tuple[bool, str]:
    """
    Verifies user credentials.
    Returns: (success: bool, message: str)
    """
    init_db()
    email_clean = email.strip().lower()

    if not email_clean or not password:
        return False, "Please enter both email and password."

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash, salt FROM users WHERE email = ?", (email_clean,))
        user = cursor.fetchone()

    if not user:
        return False, "No account found with this email. Please check or create a new account."

    stored_hash = user["password_hash"]
    salt = user["salt"]
    computed_hash, _ = hash_password(password, salt)

    if secrets.compare_digest(stored_hash, computed_hash):
        return True, "Login successful."
    else:
        return False, "Incorrect password. Please try again."


def get_total_users() -> int:
    """Returns the total number of registered accounts."""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        return row["count"] if row else 0
