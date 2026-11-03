"""Seeded faults for measuring test effectiveness.

Each fault is a deliberate, named bug that is switched off unless its name
appears in the TICKET_DROP_FAULTS environment variable. The clean application
never enables one. The catalogue below describes what each fault breaks, so a
result can be traced to the bug that caused it.
"""

CATALOGUE: dict[str, str] = {
    "seat_checked_before_lock": (
        "add_seat reads seat availability before taking the write lock and then claims the seat with an unconditional "
        "UPDATE, so two concurrent requests can both succeed and the later one silently takes the seat from the earlier "
        "holder (a 50 ms sleep in the faulty branch widens the race window); violates R2."
    ),
    "limit_ignores_owned_tickets": (
        "The four-seat limit counts only seats in the open hold and ignores tickets the account already owns, so an "
        "account that bought four seats can hold four more; violates R3."
    ),
    "hold_expiry_boundary_exclusive": (
        "Expiry uses expires_ms < now instead of <=, so at the exact expiry instant the hold is still active and its "
        "seats are not yet available; violates R4."
    ),
    "timeout_leaves_hold_paying": (
        "After a gateway timeout the hold is not put back to 'active', so it stays 'paying' for ever: the fan cannot "
        "retry, release or change seats, and expiry never frees the seats; violates R6."
    ),
    "idempotency_reruns_failed_payment": (
        "A repeated checkout whose first attempt was declined or timed out deletes the stored result and runs the "
        "payment again, so the same key can return a different result and charge after a first decline; violates R7."
    ),
    "client_sets_amount": (
        "Checkout accepts an amount_cents field from the client and charges that instead of the server's price "
        "total; violates R8."
    ),
    "remove_seat_from_any_hold": (
        "Releasing a single seat checks only that the seat is held, not that it is in the caller's hold, so a fan "
        "with any open hold can release another account's held seat; violates R9 (and R13)."
    ),
    "seat_rate_limit_per_session": (
        "The seat-change rate limit is keyed on the session token instead of the account, so signing in again (or "
        "using several sessions) gives a fresh allowance and bypasses the limit; violates R10."
    ),
    "map_stale_after_failed_seat_change": (
        "Front end: after a seat request fails (for example 'seat taken') the map is not refreshed, so the seat keeps "
        "showing as available until the next 4-second poll; violates R11."
    ),
    "release_hold_leaves_seats_held": (
        "Releasing the whole hold closes the hold but its seat update has a wrong status condition that matches "
        "nothing, so the seats stay 'held' under a closed hold and never return to sale; violates R13."
    ),
}


def on(settings, name: str) -> bool:
    if name not in CATALOGUE:
        raise KeyError(f"unknown fault {name!r}")
    return name in settings.faults
