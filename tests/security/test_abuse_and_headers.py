"""R10 rate limits, and the protective HTTP headers every response carries."""

import pytest

pytestmark = pytest.mark.security


def test_rapid_seat_changes_are_limited(sign_in):
    """Burst of 10 allowed, then 429 with Retry-After. Each request toggles the same seat."""
    mei = sign_in("mei")
    codes = []
    for i in range(14):
        response = mei.hold("C-09") if i % 2 == 0 else mei.unhold("C-09")
        codes.append(response.status_code)
        if response.status_code == 429:
            assert int(response.headers["Retry-After"]) >= 1
            assert response.json()["error"]["code"] == "too_many_requests"
    assert codes[:10] == [200] * 10
    assert 429 in codes[10:]


def test_one_fans_rate_limit_does_not_affect_another(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    for i in range(14):
        mei.hold("C-09") if i % 2 == 0 else mei.unhold("C-09")
    assert arjun.hold("D-01").status_code == 200


def test_repeated_failed_sign_ins_are_slowed_down(client):
    for _ in range(10):
        assert client.post("/api/login", json={"username": "mei", "password": "guess"}).status_code == 401
    blocked = client.post("/api/login", json={"username": "mei", "password": "guess"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    # The right password is also refused while blocked: the limit protects the account from guessing.
    assert client.post("/api/login", json={"username": "mei", "password": "demo-pass"}).status_code == 429


def test_successful_sign_ins_are_not_limited(client):
    for _ in range(15):
        assert client.post("/api/login", json={"username": "mei", "password": "demo-pass"}).status_code == 200


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


def test_api_responses_are_not_cached(sign_in):
    mei = sign_in("mei")
    assert mei.client.get("/api/hold", headers=mei.headers).headers["Cache-Control"] == "no-store"


def test_interactive_api_docs_are_not_served(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
