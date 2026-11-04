"""Booking rules: holding seats, releasing them, expiry and checkout.

Every function that changes state runs inside BEGIN IMMEDIATE, which takes
SQLite's write lock before reading. Two requests can therefore never both
read a seat as available and both claim it: the second one waits, then sees
the first one's result. The seat update itself is also conditional
(WHERE status = 'available'), so the rule holds even if the locking changed.
"""

import json
import uuid
from contextlib import contextmanager

from . import payments


class BookingError(Exception):
    status = 409

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status


@contextmanager
def write_transaction(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def expire_due_holds(conn, now_ms: int) -> None:
    """End every active hold whose expiry instant has been reached and free its seats.

    Must run inside a write transaction. A hold that is 'paying' is skipped:
    its seats stay protected until the gateway answers.
    """
    expired = [r["id"] for r in conn.execute(
        "SELECT id FROM holds WHERE status = 'active' AND expires_ms <= ?", (now_ms,)
    )]
    for hold_id in expired:
        conn.execute("UPDATE seats SET status = 'available', hold_id = NULL WHERE hold_id = ? AND status = 'held'", (hold_id,))
        conn.execute("UPDATE holds SET status = 'expired' WHERE id = ?", (hold_id,))


def sale_is_open(settings, now_ms: int) -> bool:
    return settings.sale_opens_at_ms is None or now_ms >= settings.sale_opens_at_ms


def _open_hold(conn, user_id: int):
    return conn.execute(
        "SELECT * FROM holds WHERE user_id = ? AND status IN ('active', 'paying')", (user_id,)
    ).fetchone()


def _owned_ticket_count(conn, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE user_id = ?", (user_id,)).fetchone()[0]


def hold_view(conn, user_id: int) -> dict | None:
    hold = _open_hold(conn, user_id)
    if hold is None:
        return None
    seats = [dict(r) for r in conn.execute(
        "SELECT id, row, number, tier, price_cents FROM seats WHERE hold_id = ? ORDER BY row, number", (hold["id"],)
    )]
    return {
        "id": hold["id"],
        "status": hold["status"],
        "created_ms": hold["created_ms"],
        "expires_ms": hold["expires_ms"],
        "seats": seats,
        "total_cents": sum(s["price_cents"] for s in seats),
    }


def get_hold(conn, settings, clock, user_id: int) -> dict | None:
    with write_transaction(conn):
        expire_due_holds(conn, clock.now_ms())
        return hold_view(conn, user_id)


def add_seat(conn, settings, clock, user_id: int, seat_id: str) -> dict:
    with write_transaction(conn):
        now = clock.now_ms()
        expire_due_holds(conn, now)
        if not sale_is_open(settings, now):
            raise BookingError("sale_not_open", "The sale has not opened yet.")

        seat = conn.execute("SELECT * FROM seats WHERE id = ?", (seat_id,)).fetchone()
        if seat is None:
            raise BookingError("seat_not_found", f"There is no seat {seat_id}.", 404)

        hold = _open_hold(conn, user_id)
        if hold is not None and hold["status"] == "paying":
            raise BookingError("checkout_in_progress", "A payment for your seats is in progress.")
        if hold is not None and seat["hold_id"] == hold["id"]:
            return hold_view(conn, user_id)  # Already yours: repeating the request changes nothing.

        held = 0
        if hold is not None:
            held = conn.execute("SELECT COUNT(*) FROM seats WHERE hold_id = ?", (hold["id"],)).fetchone()[0]
        if held + _owned_ticket_count(conn, user_id) >= settings.max_seats:
            raise BookingError("limit_reached", f"You can hold up to {settings.max_seats} tickets.")

        if hold is None:
            hold_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO holds (id, user_id, created_ms, expires_ms, status) VALUES (?, ?, ?, ?, 'active')",
                (hold_id, user_id, now, now + settings.hold_seconds * 1000),
            )
        else:
            hold_id = hold["id"]

        claimed = conn.execute(
            "UPDATE seats SET status = 'held', hold_id = ? WHERE id = ? AND status = 'available'", (hold_id, seat_id)
        ).rowcount
        if claimed == 0:
            raise BookingError("seat_taken", f"Seat {seat_id} has just been taken.")
        return hold_view(conn, user_id)


def remove_seat(conn, settings, clock, user_id: int, seat_id: str) -> dict | None:
    with write_transaction(conn):
        expire_due_holds(conn, clock.now_ms())
        hold = _open_hold(conn, user_id)
        if hold is None or hold["status"] != "active":
            raise BookingError("seat_not_held", f"Seat {seat_id} is not in your hold.", 404)
        freed = conn.execute(
            "UPDATE seats SET status = 'available', hold_id = NULL WHERE id = ? AND hold_id = ?", (seat_id, hold["id"])
        ).rowcount
        if freed == 0:
            raise BookingError("seat_not_held", f"Seat {seat_id} is not in your hold.", 404)
        remaining = conn.execute("SELECT COUNT(*) FROM seats WHERE hold_id = ?", (hold["id"],)).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE holds SET status = 'released' WHERE id = ?", (hold["id"],))
        return hold_view(conn, user_id)


def release_hold(conn, settings, clock, user_id: int) -> None:
    with write_transaction(conn):
        expire_due_holds(conn, clock.now_ms())
        hold = _open_hold(conn, user_id)
        if hold is None:
            return
        if hold["status"] == "paying":
            raise BookingError("checkout_in_progress", "A payment for your seats is in progress.")
        conn.execute("UPDATE seats SET status = 'available', hold_id = NULL WHERE hold_id = ?", (hold["id"],))
        conn.execute("UPDATE holds SET status = 'released' WHERE id = ?", (hold["id"],))


def seat_map(conn, settings, clock, user_id: int) -> list[dict]:
    with write_transaction(conn):
        expire_due_holds(conn, clock.now_ms())
        hold = _open_hold(conn, user_id)
        mine = hold["id"] if hold else None
        owned = {r["seat_id"] for r in conn.execute("SELECT seat_id FROM tickets WHERE user_id = ?", (user_id,))}
        result = []
        for s in conn.execute("SELECT * FROM seats ORDER BY rowid"):
            if s["id"] in owned or (mine is not None and s["hold_id"] == mine):
                state = "mine"
            elif s["status"] == "available":
                state = "available"
            else:
                state = "taken"
            result.append({
                "id": s["id"], "row": s["row"], "number": s["number"], "block": s["block"],
                "tier": s["tier"], "price_cents": s["price_cents"], "state": state,
            })
        return result


def checkout(conn, settings, clock, user_id: int, idempotency_key: str, card_number: str) -> tuple[int, dict]:
    """Pay for the open hold. Returns (HTTP status, response body).

    Three steps, so the slow gateway call never holds the database lock:
    1. Record a pending payment and mark the hold 'paying' (expiry skips it).
    2. Call the gateway outside any transaction.
    3. Settle: issue tickets on success, or put the hold back to 'active'.
    A repeated request with the same idempotency key returns the stored result.
    """
    with write_transaction(conn):
        now = clock.now_ms()
        previous = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? AND idempotency_key = ?", (user_id, idempotency_key)
        ).fetchone()
        if previous is not None:
            if previous["outcome"] == "pending":
                raise BookingError("checkout_in_progress", "This payment is still being processed.")
            return previous["response_status"], json.loads(previous["response_body"])

        expire_due_holds(conn, now)
        hold = _open_hold(conn, user_id)
        if hold is None:
            raise BookingError("no_hold", "You have no seats on hold. Your hold may have expired.")
        if hold["status"] == "paying":
            raise BookingError("checkout_in_progress", "A payment for your seats is in progress.")
        amount = conn.execute(
            "SELECT COALESCE(SUM(price_cents), 0) FROM seats WHERE hold_id = ?", (hold["id"],)
        ).fetchone()[0]
        payment_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO payments (id, user_id, hold_id, idempotency_key, amount_cents, outcome, created_ms)"
            " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (payment_id, user_id, hold["id"], idempotency_key, amount, now),
        )
        conn.execute("UPDATE holds SET status = 'paying' WHERE id = ?", (hold["id"],))

    try:
        outcome = payments.charge(conn, payment_id, card_number, amount, clock.now_ms(), settings.payment_timeout_seconds)
    except Exception:
        outcome = "timeout"

    with write_transaction(conn):
        now = clock.now_ms()
        if outcome == "succeeded":
            seats = [r["id"] for r in conn.execute("SELECT id FROM seats WHERE hold_id = ?", (hold["id"],))]
            tickets = []
            for seat_id in seats:
                ticket_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO tickets (id, user_id, seat_id, payment_id, issued_ms) VALUES (?, ?, ?, ?, ?)",
                    (ticket_id, user_id, seat_id, payment_id, now),
                )
                tickets.append(ticket_id)
            conn.execute("UPDATE seats SET status = 'sold', hold_id = NULL WHERE hold_id = ?", (hold["id"],))
            conn.execute("UPDATE holds SET status = 'paid' WHERE id = ?", (hold["id"],))
            status, body = 200, {
                "payment": {"id": payment_id, "outcome": outcome, "amount_cents": amount},
                "tickets": [ticket_view(conn, t) for t in tickets],
            }
        else:
            # Seats stay held until the original expiry, so the fan can retry.
            conn.execute("UPDATE holds SET status = 'active' WHERE id = ?", (hold["id"],))
            expire_due_holds(conn, now)
            if outcome == "declined":
                status, body = 402, {"error": {"code": "payment_declined", "message": "The card was declined. Your seats are still held."}}
            else:
                status, body = 504, {"error": {"code": "payment_timeout", "message": "The payment service did not answer. You were not charged."}}
        conn.execute(
            "UPDATE payments SET outcome = ?, response_status = ?, response_body = ? WHERE id = ?",
            (outcome, status, json.dumps(body), payment_id),
        )
    return status, body


def ticket_view(conn, ticket_id: str) -> dict:
    t = conn.execute(
        "SELECT t.id, t.seat_id, t.issued_ms, s.row, s.number, s.tier, s.price_cents"
        " FROM tickets t JOIN seats s ON s.id = t.seat_id WHERE t.id = ?", (ticket_id,)
    ).fetchone()
    return dict(t)


def list_tickets(conn, user_id: int) -> list[dict]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM tickets WHERE user_id = ? ORDER BY seat_id", (user_id,))]
    return [ticket_view(conn, i) for i in ids]


def get_ticket(conn, user_id: int, ticket_id: str) -> dict:
    row = conn.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    # Someone else's ticket answers exactly like a missing one, so IDs cannot be probed.
    if row is None or row["user_id"] != user_id:
        raise BookingError("ticket_not_found", "Ticket not found.", 404)
    return ticket_view(conn, ticket_id)
