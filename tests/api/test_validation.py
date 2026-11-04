"""R12: malformed input is refused and changes nothing.

Equivalence classes for a seat ID: valid (row A-T, two digits), wrong row
letter, lower case, wrong digit count, injection-shaped text, wrong type.
"""

import pytest

BAD_SEAT_IDS = ["Z-01", "c-09", "C-9", "C-009", "C09", "", "C-09'; DROP TABLE seats;--", "C-09\n", 9, None]


@pytest.mark.parametrize("seat_id", BAD_SEAT_IDS)
def test_malformed_seat_ids_are_refused(sign_in, query, seat_id):
    lejie = sign_in("lejie")
    response = lejie.client.post("/api/hold/seats", json={"seat_id": seat_id}, headers=lejie.headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert query("SELECT COUNT(*) AS n FROM holds") == [{"n": 0}]
    assert query("SELECT COUNT(*) AS n FROM seats") == [{"n": 510}]


@pytest.mark.parametrize("body", [{}, {"seat_id": "C-09", "extra": 1}, ["C-09"]])
def test_malformed_bodies_are_refused(sign_in, body):
    lejie = sign_in("lejie")
    response = lejie.client.post("/api/hold/seats", json=body, headers=lejie.headers)
    assert response.status_code == 422


@pytest.mark.parametrize("card", ["", "abcd", "4242", "4242-4242-4242-4242", "4" * 40])
def test_malformed_card_numbers_are_refused(sign_in, query, card):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = lejie.checkout(card)
    assert response.status_code == 422
    assert query("SELECT COUNT(*) AS n FROM payments") == [{"n": 0}]


@pytest.mark.parametrize("key", ["short", "has space here", "x" * 65, "semi;colon!"])
def test_malformed_idempotency_keys_are_refused(sign_in, key):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    response = lejie.checkout(key=key)
    assert response.status_code == 400


def test_an_unknown_api_address_answers_in_the_error_shape(client):
    response = client.get("/api/no-such-thing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "There is nothing at this address."}}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method,path,allowed", [("post", "/api/event", "GET"), ("get", "/api/checkout", "POST")])
def test_a_wrong_method_answers_in_the_error_shape(client, method, path, allowed):
    response = client.request(method.upper(), path)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["Allow"] == allowed


def test_an_unknown_page_outside_the_api_is_a_plain_404(client):
    """Static files keep the framework's own answer; only /api promises the error shape."""
    response = client.get("/no-such-page.html")
    assert response.status_code == 404
    assert "error" not in response.json()


def test_errors_never_leak_internals(sign_in):
    lejie = sign_in("lejie")
    response = lejie.client.post("/api/hold/seats", content=b"{not json", headers={**lejie.headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "Traceback" not in response.text and "sqlite" not in response.text.lower()
