"""R12: malformed input is refused and changes nothing.

Equivalence classes for a seat ID: valid (row A-T, two digits), wrong row
letter, lower case, wrong digit count, injection-shaped text, wrong type.
"""

import pytest

BAD_SEAT_IDS = ["Z-01", "c-09", "C-9", "C-009", "C09", "", "C-09'; DROP TABLE seats;--", "C-09\n", 9, None]


@pytest.mark.parametrize("seat_id", BAD_SEAT_IDS)
def test_malformed_seat_ids_are_refused(sign_in, query, seat_id):
    mei = sign_in("mei")
    response = mei.client.post("/api/hold/seats", json={"seat_id": seat_id}, headers=mei.headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert query("SELECT COUNT(*) AS n FROM holds") == [{"n": 0}]
    assert query("SELECT COUNT(*) AS n FROM seats") == [{"n": 510}]


@pytest.mark.parametrize("body", [{}, {"seat_id": "C-09", "extra": 1}, ["C-09"]])
def test_malformed_bodies_are_refused(sign_in, body):
    mei = sign_in("mei")
    response = mei.client.post("/api/hold/seats", json=body, headers=mei.headers)
    assert response.status_code == 422


@pytest.mark.parametrize("card", ["", "abcd", "4242", "4242-4242-4242-4242", "4" * 40])
def test_malformed_card_numbers_are_refused(sign_in, query, card):
    mei = sign_in("mei")
    mei.hold("C-09")
    response = mei.checkout(card)
    assert response.status_code == 422
    assert query("SELECT COUNT(*) AS n FROM payments") == [{"n": 0}]


@pytest.mark.parametrize("key", ["short", "has space here", "x" * 65, "semi;colon!"])
def test_malformed_idempotency_keys_are_refused(sign_in, key):
    mei = sign_in("mei")
    mei.hold("C-09")
    response = mei.checkout(key=key)
    assert response.status_code == 400


def test_errors_never_leak_internals(sign_in):
    mei = sign_in("mei")
    response = mei.client.post("/api/hold/seats", content=b"{not json", headers={**mei.headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "Traceback" not in response.text and "sqlite" not in response.text.lower()
