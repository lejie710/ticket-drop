"""A mock payment gateway. No real money or card network is involved.

The card number decides the outcome, like the test cards real payment
providers publish. Unknown card numbers are declined.
"""

import time

SUCCESS_CARD = "4242424242424242"
DECLINE_CARD = "4000000000000002"
TIMEOUT_CARD = "4000000000000408"


def normalise(card_number: str) -> str:
    return card_number.replace(" ", "")


def charge(conn, payment_id: str, card_number: str, amount_cents: int, now_ms: int, timeout_seconds: float) -> str:
    """Return 'succeeded', 'declined' or 'timeout'. Only a success writes to the ledger."""
    card = normalise(card_number)
    if card == TIMEOUT_CARD:
        # The gateway never answers; the caller gives up after its timeout.
        time.sleep(timeout_seconds)
        return "timeout"
    if card != SUCCESS_CARD:
        return "declined"
    conn.execute(
        "INSERT INTO charges (payment_id, amount_cents, created_ms) VALUES (?, ?, ?)",
        (payment_id, amount_cents, now_ms),
    )
    return "succeeded"
