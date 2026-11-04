"""R5 to R8: paying, failing to pay, retrying, and who sets the price.

The charges table is the mock gateway's ledger. Checking it, not just the
HTTP response, is how these tests know whether money actually moved.
"""

from tests.conftest import DECLINE, SUCCESS, TIMEOUT


def charges(query):
    return query("SELECT payment_id, amount_cents FROM charges")


def test_successful_payment_issues_one_ticket_per_seat(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    lejie.hold("H-03")
    response = lejie.checkout(SUCCESS)
    assert response.status_code == 200
    body = response.json()
    assert sorted(t["seat_id"] for t in body["tickets"]) == ["C-09", "H-03"]
    assert body["payment"]["amount_cents"] == 38800 + 26800
    assert charges(query) == [{"payment_id": body["payment"]["id"], "amount_cents": 65600}]
    assert lejie.current_hold() is None
    assert {s for s, state in lejie.seat_states().items() if state == "mine"} == {"C-09", "H-03"}
    assert query("SELECT status FROM seats WHERE id IN ('C-09', 'H-03')") == [{"status": "sold"}] * 2


def test_sold_seats_stay_taken_for_everyone_else(sign_in, clock):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    lejie.checkout()
    clock.advance(10 * 60_000)  # Long after the hold would have expired.
    assert arjun.seat_states()["C-09"] == "taken"
    assert arjun.hold("C-09").json()["error"]["code"] == "seat_taken"


def test_declined_card_charges_nothing_and_keeps_the_seats(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = lejie.checkout(DECLINE)
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "payment_declined"
    assert charges(query) == []
    assert lejie.tickets() == []
    assert [s["id"] for s in lejie.current_hold()["seats"]] == ["C-09"]


def test_retry_after_a_decline_succeeds(sign_in):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    assert lejie.checkout(DECLINE).status_code == 402
    assert lejie.checkout(SUCCESS).status_code == 200
    assert [t["seat_id"] for t in lejie.tickets()] == ["C-09"]


def test_gateway_timeout_charges_nothing_and_keeps_the_seats(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = lejie.checkout(TIMEOUT)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "payment_timeout"
    assert charges(query) == []
    assert lejie.current_hold()["status"] == "active"


def test_a_declined_hold_still_expires_on_time(sign_in, clock):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    lejie.checkout(DECLINE)
    clock.advance(300_000)
    assert arjun.hold("C-09").status_code == 200


def test_repeating_a_checkout_with_the_same_key_charges_once(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    first = lejie.checkout(SUCCESS, key="order-attempt-1")
    second = lejie.checkout(SUCCESS, key="order-attempt-1")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()  # The stored result, not a new payment.
    assert len(charges(query)) == 1
    assert len(lejie.tickets()) == 1


def test_repeating_a_declined_checkout_returns_the_same_decline(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    first = lejie.checkout(DECLINE, key="order-attempt-2")
    # Same key, different card: the key identifies the original attempt, so its result is returned.
    second = lejie.checkout(SUCCESS, key="order-attempt-2")
    assert first.status_code == second.status_code == 402
    assert charges(query) == []


def test_checkout_needs_an_idempotency_key(sign_in, client):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = client.post("/api/checkout", json={"card_number": SUCCESS}, headers=lejie.headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"


def test_checkout_without_a_hold(sign_in):
    response = sign_in("lejie").checkout()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_hold"


def test_the_client_cannot_set_the_price(sign_in, client, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = client.post("/api/checkout", json={"card_number": SUCCESS, "amount_cents": 1},
                           headers={**lejie.headers, "Idempotency-Key": "cheap-attempt"})
    assert response.status_code == 422
    assert charges(query) == []
    paid = lejie.checkout(SUCCESS).json()
    assert paid["payment"]["amount_cents"] == 38800


def test_seats_cannot_change_while_a_payment_is_in_flight(sign_in, client, query):
    """A hold marked 'paying' refuses changes. Simulated by setting the status directly."""
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    import sqlite3
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute("UPDATE holds SET status = 'paying'")
    conn.commit()
    conn.close()
    assert lejie.hold("C-10").json()["error"]["code"] == "checkout_in_progress"
    assert lejie.release_all().json()["error"]["code"] == "checkout_in_progress"
