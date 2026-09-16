"""
Authentication helpers: password hashing (PBKDF2-HMAC-SHA256, stdlib only,
no external dependency needed) and login/session logic.
"""
import hashlib
import os
import secrets
from datetime import datetime

PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex). Generates a new salt if not provided."""
    if salt is None:
        salt = secrets.token_hex(16)
    salt_bytes = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PBKDF2_ITERATIONS)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    test_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(test_hash, password_hash)


class AuthError(Exception):
    pass


class Session:
    """Holds the currently logged-in user for the running application."""
    current_user = None  # dict with id, username, full_name, role

    @classmethod
    def login(cls, conn, username: str, password: str) -> dict:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
        ).fetchone()
        if row is None:
            raise AuthError("Invalid username or password.")
        if not verify_password(password, row["password_hash"], row["salt"]):
            raise AuthError("Invalid username or password.")
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), row["id"]),
        )
        conn.commit()
        cls.current_user = dict(row)
        return cls.current_user

    @classmethod
    def logout(cls):
        cls.current_user = None

    @classmethod
    def require_role(cls, *roles):
        if cls.current_user is None:
            raise AuthError("Not logged in.")
        if cls.current_user["role"] not in roles and cls.current_user["role"] != "admin":
            raise AuthError("You do not have permission to perform this action.")


# ---------------------------------------------------------------------
# Forgot-password: self-service reset via a security question, since this
# is an offline desktop app with no email server to send reset links.
# An admin can also always reset a user's password directly from the
# Users screen, independent of whether a security question is set.
# ---------------------------------------------------------------------

def set_security_question(conn, user_id: int, question: str, answer: str):
    """Set/replace a user's recovery question. Answer is hashed the same way
    as a password - never stored or compared in plain text."""
    if not question or not question.strip():
        raise AuthError("Security question cannot be empty.")
    if not answer or not answer.strip():
        raise AuthError("Security answer cannot be empty.")
    ans_hash, salt = hash_password(answer.strip().lower())
    conn.execute(
        "UPDATE users SET security_question=?, security_answer_hash=?, security_answer_salt=? WHERE id=?",
        (question.strip(), ans_hash, salt, user_id),
    )
    conn.commit()


def get_security_question(conn, username: str):
    """Returns the recovery question for a username, or None if the account
    doesn't exist, is inactive, or has no recovery question set."""
    row = conn.execute(
        "SELECT security_question FROM users WHERE username = ? AND active = 1", (username,)
    ).fetchone()
    if row is None or not row["security_question"]:
        return None
    return row["security_question"]


def reset_password_with_security_answer(conn, username: str, answer: str, new_password: str):
    """Verifies the security answer and, if correct, sets a new password.
    Raises AuthError with a safe, non-revealing message on any failure."""
    if not new_password or len(new_password) < 4:
        raise AuthError("New password must be at least 4 characters.")
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
    ).fetchone()
    if row is None or not row["security_answer_hash"]:
        raise AuthError(
            "No recovery question is set up for this account. "
            "Ask an administrator to reset your password instead."
        )
    if not verify_password((answer or "").strip().lower(), row["security_answer_hash"], row["security_answer_salt"]):
        raise AuthError("That answer doesn't match our records.")
    pwd_hash, salt = hash_password(new_password)
    conn.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (pwd_hash, salt, row["id"]))
    conn.commit()
