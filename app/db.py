"""SQLite schema, connections and the deterministic seed data."""

import hashlib
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    pw_salt BLOB NOT NULL,
    pw_hash BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS holds (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_ms INTEGER NOT NULL,
    expires_ms INTEGER NOT NULL,
    -- 'paying' protects the seats while the payment gateway is called.
    status TEXT NOT NULL CHECK (status IN ('active', 'paying', 'paid', 'expired', 'released'))
);

-- At most one open hold per account.
CREATE UNIQUE INDEX IF NOT EXISTS one_open_hold_per_user
    ON holds(user_id) WHERE status IN ('active', 'paying');

CREATE TABLE IF NOT EXISTS seats (
    id TEXT PRIMARY KEY,
    row TEXT NOT NULL,
    number INTEGER NOT NULL,
    block INTEGER NOT NULL,
    tier INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'held', 'sold')),
    hold_id TEXT REFERENCES holds(id),
    CHECK ((status = 'held') = (hold_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS holds_due ON holds(status, expires_ms);
CREATE INDEX IF NOT EXISTS seats_by_hold ON seats(hold_id);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    hold_id TEXT NOT NULL REFERENCES holds(id),
    idempotency_key TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'succeeded', 'declined', 'timeout')),
    response_status INTEGER,
    response_body TEXT,
    created_ms INTEGER NOT NULL,
    UNIQUE (user_id, idempotency_key)
);

-- The mock gateway's ledger: money that actually moved.
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES payments(id),
    amount_cents INTEGER NOT NULL,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    -- The last line of defence against selling a seat twice.
    seat_id TEXT NOT NULL UNIQUE REFERENCES seats(id),
    payment_id TEXT NOT NULL REFERENCES payments(id),
    issued_ms INTEGER NOT NULL
);
"""

ROWS = [chr(ord("A") + i) for i in range(20)]
PRICES_CENTS = {1: 38800, 2: 26800, 3: 16800}
DEMO_PASSWORD = "demo-pass"
NAMED_USERS = [("mei", "Mei"), ("arjun", "Arjun"), ("siti", "Siti"), ("wei", "Wei")]
LOAD_TEST_USERS = 500


def tier_for_row(row_index: int) -> int:
    if row_index < 5:
        return 1
    if row_index < 12:
        return 2
    return 3


def seat_layout():
    """Rows A to T. Row A has 16 seats and each row behind it one more: 510 seats in three blocks."""
    for i, row in enumerate(ROWS):
        count = 16 + i
        block_size = -(-count // 3)
        for n in range(1, count + 1):
            if n <= block_size:
                block = 1
            elif n <= count - block_size:
                block = 2
            else:
                block = 3
            tier = tier_for_row(i)
            yield (f"{row}-{n:02d}", row, n, block, tier, PRICES_CENTS[tier])


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def initialise(path: str) -> None:
    """Create the schema and seed data if the database is empty."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        # WAL lets readers continue while a write is in progress. The mode is
        # stored in the file, so it is set once here rather than per connection.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0] == 0:
            seed(conn)
    finally:
        conn.close()


def add_sample_sales(path: str, fraction: float, seed_value: int = 2027) -> int:
    """Mark a share of seats as already sold to sample fan accounts, for demos and screenshots.

    Sample data only: payments are recorded with idempotency keys starting
    'sample-' and no gateway charge. Runs once; a database that already has
    tickets is left alone. Returns the number of seats sold.
    """
    import random
    import uuid

    conn = connect(path)
    try:
        if conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]:
            return 0
        rng = random.Random(seed_value)
        seats = [dict(r) for r in conn.execute("SELECT id, row, price_cents FROM seats ORDER BY rowid")]
        # Front rows sell faster, as they do at real sales.
        chosen = [s for s in seats if rng.random() < fraction * (1.35 - 0.035 * (ord(s["row"]) - ord("A")))]
        fans = [r["id"] for r in conn.execute("SELECT id FROM users WHERE username LIKE 'fan%' ORDER BY id")]
        conn.execute("BEGIN")
        for i in range(0, len(chosen), 4):
            group = chosen[i:i + 4]
            user_id = fans[(i // 4) % len(fans)]
            hold_id, payment_id = uuid.uuid4().hex, uuid.uuid4().hex
            conn.execute("INSERT INTO holds VALUES (?, ?, 0, 0, 'paid')", (hold_id, user_id))
            conn.execute(
                "INSERT INTO payments (id, user_id, hold_id, idempotency_key, amount_cents, outcome, created_ms)"
                " VALUES (?, ?, ?, ?, ?, 'succeeded', 0)",
                (payment_id, user_id, hold_id, f"sample-{payment_id}", sum(s["price_cents"] for s in group)),
            )
            for s in group:
                conn.execute("INSERT INTO tickets VALUES (?, ?, ?, ?, 0)", (uuid.uuid4().hex, user_id, s["id"], payment_id))
                conn.execute("UPDATE seats SET status = 'sold' WHERE id = ?", (s["id"],))
        conn.execute("COMMIT")
        return len(chosen)
    finally:
        conn.close()


def seed(conn: sqlite3.Connection) -> None:
    # Every demo account shares one password, so the slow hash is computed once.
    # This is a demo shortcut, recorded in docs/DESIGN.md as a known limitation.
    salt = os.urandom(16)
    pw_hash = hash_password(DEMO_PASSWORD, salt)
    users = list(NAMED_USERS) + [(f"fan{i:03d}", f"Fan {i:03d}") for i in range(1, LOAD_TEST_USERS + 1)]
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO users (username, display_name, pw_salt, pw_hash) VALUES (?, ?, ?, ?)",
        [(u, d, salt, pw_hash) for u, d in users],
    )
    conn.executemany(
        "INSERT INTO seats (id, row, number, block, tier, price_cents, status) VALUES (?, ?, ?, ?, ?, ?, 'available')",
        list(seat_layout()),
    )
    conn.execute("COMMIT")
