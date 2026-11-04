"""Token login for the seeded demo accounts. There is no registration."""

import hashlib
import hmac
import secrets

from . import db


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(conn, username: str, password: str, now_ms: int) -> dict | None:
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        # Spend the same effort as a real check so response time does not reveal valid usernames.
        db.hash_password(password, b"\x00" * 16)
        return None
    if not hmac.compare_digest(db.hash_password(password, user["pw_salt"]), user["pw_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_ms) VALUES (?, ?, ?)", (_token_hash(token), user["id"], now_ms)
    )
    return {"token": token, "user": {"username": user["username"], "display_name": user["display_name"]}}


def user_for_token(conn, token: str):
    return conn.execute(
        "SELECT u.id, u.username, u.display_name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()


def logout(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
