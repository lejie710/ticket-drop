"""R9: one fan cannot read or change another fan's holds, payments or tickets.

These tests play the attacker: a signed-in fan who knows, or guesses,
identifiers that belong to someone else.
"""

import sqlite3

import pytest

pytestmark = pytest.mark.security


def test_cannot_release_someone_elses_seat(sign_in):
    lejie, attacker = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    attacker.hold("D-01")  # The attacker has a hold of their own.
    assert attacker.unhold("C-09").status_code == 404
    assert attacker.release_all().status_code == 204  # Releases only the attacker's own hold.
    assert lejie.seat_states()["C-09"] == "mine"
    assert attacker.seat_states()["D-01"] == "available"


def test_cannot_pay_for_someone_elses_hold(sign_in, query):
    lejie, attacker = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    response = attacker.checkout()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_hold"
    assert query("SELECT COUNT(*) AS n FROM tickets") == [{"n": 0}]


def test_cannot_replay_someone_elses_idempotency_key(sign_in, query):
    """Keys are scoped to the account, so a leaked key reveals nothing."""
    lejie, attacker = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    lejie.checkout(key="shared-key-123")
    attacker.hold("D-02")
    response = attacker.checkout(key="shared-key-123")
    assert response.status_code == 200
    assert [t["seat_id"] for t in response.json()["tickets"]] == ["D-02"]


def test_ticket_ids_cannot_be_used_across_accounts(sign_in):
    lejie, attacker = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    ticket_id = lejie.checkout().json()["tickets"][0]["id"]
    assert attacker.client.get(f"/api/tickets/{ticket_id}", headers=attacker.headers).status_code == 404


def test_ticket_ids_are_not_guessable(sign_in):
    lejie = sign_in("lejie")
    for seat in ["C-09", "C-10"]:
        lejie.hold(seat)
    ids = [t["id"] for t in lejie.checkout().json()["tickets"]]
    assert all(len(i) == 32 for i in ids)
    assert int(ids[0], 16) - int(ids[1], 16) not in (-1, 1)  # Not sequential.


def test_tokens_are_stored_only_as_hashes(sign_in, db_path):
    lejie = sign_in("lejie")
    token = lejie.headers["Authorization"].removeprefix("Bearer ")
    conn = sqlite3.connect(db_path)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    conn.close()
    assert token not in stored
    assert all(len(s) == 64 for s in stored)


def test_test_hooks_are_off_by_default(client):
    """The clock-control route exists only when TICKET_DROP_TEST_HOOKS=1."""
    response = client.post("/api/_test/clock", json={"advance_ms": 600_000})
    assert response.status_code in (404, 405)
    assert client.get("/api/event").json()["server_now_ms"] < 1_800_000_000_000 + 600_000
