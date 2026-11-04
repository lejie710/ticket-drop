"""R10 rate limits, and the protective HTTP headers every response carries.

The rate limiters read a test-controlled monotonic clock (the monotonic
fixture), so "ten quick requests" means exactly that on any machine.
"""

import sqlite3

import pytest

from app import service
from app.main import SECURITY_HEADERS

pytestmark = pytest.mark.security


def test_rapid_seat_changes_are_limited(sign_in, monotonic):
    """Burst of 10 allowed, then 429 with Retry-After. Each request toggles the same seat."""
    lejie = sign_in("lejie")
    codes = []
    for i in range(14):
        response = lejie.hold("C-09") if i % 2 == 0 else lejie.unhold("C-09")
        codes.append(response.status_code)
        if response.status_code == 429:
            assert int(response.headers["Retry-After"]) >= 1
            assert response.json()["error"]["code"] == "too_many_requests"
    assert codes[:10] == [200] * 10
    assert codes[10] == 429, codes
    monotonic.advance(1)  # Five tokens a second refill the bucket.
    assert lejie.hold("C-09").status_code == 200


def test_signing_in_again_does_not_reset_the_rate_limit(sign_in):
    """Added after fault injection: the limit belongs to the account, not to one session."""
    first, second = sign_in("lejie"), sign_in("lejie")
    codes = []
    for i in range(14):
        fan = first if i % 2 == 0 else second
        response = fan.hold("C-09") if (i // 2) % 2 == 0 else fan.unhold("C-09")
        codes.append(response.status_code)
    assert 429 not in codes[:10], codes  # Ten changes across both sessions spend the account's burst...
    assert codes[10] == 429, codes  # ...so the eleventh is refused, whichever session sends it.


def test_one_fans_rate_limit_does_not_affect_another(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    for i in range(14):
        lejie.hold("C-09") if i % 2 == 0 else lejie.unhold("C-09")
    assert arjun.hold("D-01").status_code == 200


def test_repeated_failed_sign_ins_are_slowed_down(client, monotonic):
    for _ in range(10):
        assert client.post("/api/login", json={"username": "lejie", "password": "guess"}).status_code == 401
    blocked = client.post("/api/login", json={"username": "lejie", "password": "guess"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) == 60
    # The right password is also refused while blocked: the limit protects the account from guessing.
    assert client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).status_code == 429
    monotonic.advance(60)  # The one-minute window has passed.
    assert client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).status_code == 200


def test_successful_sign_ins_are_not_limited(client):
    for _ in range(15):
        assert client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).status_code == 200


@pytest.mark.parametrize("path", ["/", "/app.js", "/api/event"])
def test_security_headers_on_every_response(client, path):
    headers = client.get(path).headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_server_errors_carry_the_same_headers(make_client, monkeypatch):
    """A 500 is answered outside the middleware stack, so it needs the headers added by hand."""
    client = make_client(raise_server_exceptions=False)
    token = client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).json()["token"]

    def locked(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(service, "write_transaction", locked)
    response = client.post("/api/hold/seats", json={"seat_id": "C-09"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "server_error"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name
    assert response.headers["Cache-Control"] == "no-store"


def test_api_responses_are_not_cached(sign_in):
    lejie = sign_in("lejie")
    assert lejie.client.get("/api/hold", headers=lejie.headers).headers["Cache-Control"] == "no-store"


def test_interactive_api_docs_are_not_served(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
