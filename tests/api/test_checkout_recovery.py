"""R5 to R7 on the paths between the gateway call and settling (DEF-007).

The gateway is the slow, unreliable step. These tests force things to go
wrong around it: settling fails after the money moved, the hold expires
while the gateway is deciding, a seat change arrives mid-payment.
"""

import sqlite3

from fastapi.testclient import TestClient

from app import payments, service
from app.config import Settings
from app.main import create_app
from tests.conftest import DECLINE, FAULTS, SUCCESS, Fan


def test_settle_failure_is_finished_by_a_retry_without_charging_again(db_path, clock, query, monkeypatch):
    client = TestClient(create_app(Settings(db_path=db_path, payment_timeout_seconds=0, faults=FAULTS), clock),
                        raise_server_exceptions=False)
    token = client.post("/api/login", json={"username": "mei", "password": "demo-pass"}).json()["token"]
    mei = Fan(client, token, "mei")
    mei.hold("C-09")

    # Let the first transaction (reserve) through, then make every later one fail
    # as if the database stayed locked: the gateway has already taken the money.
    real_transaction = service.write_transaction
    state = {"calls": 0, "broken": True}

    def failing_transaction(conn):
        state["calls"] += 1
        if state["broken"] and state["calls"] >= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_transaction(conn)

    monkeypatch.setattr(service, "write_transaction", failing_transaction)
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    first = mei.checkout(SUCCESS, key="attempt-recover-1")
    assert first.status_code == 500
    assert first.json()["error"]["code"] == "server_error"  # JSON, not a plain-text crash page.
    assert "locked" not in first.text
    assert query("SELECT COUNT(*) AS n FROM charges") == [{"n": 1}]  # The money moved...
    assert query("SELECT COUNT(*) AS n FROM tickets") == [{"n": 0}]  # ...but no tickets yet.

    state["broken"] = False  # The database recovers; the fan's app retries with the same key.
    retry = mei.checkout(SUCCESS, key="attempt-recover-1")
    assert retry.status_code == 200
    assert [t["seat_id"] for t in retry.json()["tickets"]] == ["C-09"]
    assert query("SELECT COUNT(*) AS n FROM charges") == [{"n": 1}]  # Still one charge.
    assert mei.checkout(SUCCESS, key="attempt-recover-1").json() == retry.json()


def test_settle_survives_a_briefly_busy_database(sign_in, query, monkeypatch):
    mei = sign_in("mei")
    mei.hold("C-09")
    real_settle = service._settle_once
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_settle(*args)

    monkeypatch.setattr(service, "_settle_once", flaky)
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    assert mei.checkout(SUCCESS).status_code == 200
    assert calls["n"] == 2
    assert query("SELECT COUNT(*) AS n FROM tickets") == [{"n": 1}]


def test_hold_expiring_during_a_declined_payment_frees_the_seats_at_once(sign_in, clock, monkeypatch):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    real_charge = payments.charge

    def slow_decline(*args):
        clock.advance(400_000)  # The gateway takes longer than the rest of the hold.
        return real_charge(*args)

    monkeypatch.setattr(payments, "charge", slow_decline)
    assert mei.checkout(DECLINE).status_code == 402
    assert mei.current_hold() is None
    assert arjun.hold("C-09").status_code == 200


def test_a_payment_started_in_time_is_honoured_after_the_expiry(sign_in, clock, monkeypatch):
    """Design rule: the hold is protected while 'paying', so a success that arrives late still issues tickets."""
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    real_charge = payments.charge

    def slow_success(*args):
        clock.advance(400_000)
        return real_charge(*args)

    monkeypatch.setattr(payments, "charge", slow_success)
    assert mei.checkout(SUCCESS).status_code == 200
    assert arjun.hold("C-09").json()["error"]["code"] == "seat_taken"


def test_releasing_one_seat_mid_payment_is_refused_clearly(sign_in, client):
    mei = sign_in("mei")
    mei.hold("C-09")
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute("UPDATE holds SET status = 'paying'")
    conn.commit()
    conn.close()
    response = mei.unhold("C-09")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "checkout_in_progress"
