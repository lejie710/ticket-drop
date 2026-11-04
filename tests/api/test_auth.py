"""R9: only signed-in fans can use their account."""

import pytest

from tests.conftest import SUCCESS

# Every route that needs a signed-in fan, each with a body and headers that would
# otherwise be accepted, so a 401 can only come from the missing or wrong token.
AUTHENTICATED_ROUTES = [
    ("post", "/api/logout", {}),
    ("get", "/api/me", {}),
    ("get", "/api/seats", {}),
    ("get", "/api/hold", {}),
    ("post", "/api/hold/seats", {"json": {"seat_id": "C-09"}}),
    ("delete", "/api/hold/seats/C-09", {}),
    ("delete", "/api/hold", {}),
    ("post", "/api/checkout", {"json": {"card_number": SUCCESS}, "headers": {"Idempotency-Key": "attempt-0001"}}),
    ("get", "/api/tickets", {}),
    ("get", "/api/tickets/" + "0" * 32, {}),
]


def test_demo_account_signs_in(client):
    response = client.post("/api/login", json={"username": "lejie", "password": "demo-pass"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"username": "lejie", "display_name": "Le Jie"}
    assert len(body["token"]) >= 40


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong_password = client.post("/api/login", json={"username": "lejie", "password": "nope"})
    unknown_user = client.post("/api/login", json={"username": "nobody", "password": "demo-pass"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    # Identical answers, so the endpoint cannot be used to discover which usernames exist.
    assert wrong_password.json() == unknown_user.json()


@pytest.mark.parametrize("token", [None, "made-up-token"], ids=["no-token", "made-up-token"])
@pytest.mark.parametrize("method,path,kwargs", AUTHENTICATED_ROUTES, ids=[f"{m} {p}" for m, p, _ in AUTHENTICATED_ROUTES])
def test_every_account_route_refuses_a_missing_or_made_up_token(client, query, token, method, path, kwargs):
    headers = dict(kwargs.get("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = {k: v for k, v in kwargs.items() if k != "headers"}
    response = client.request(method.upper(), path, headers=headers, **request)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_signed_in"
    assert query("SELECT COUNT(*) AS n FROM holds") == [{"n": 0}]
    assert query("SELECT COUNT(*) AS n FROM payments") == [{"n": 0}]


def test_signing_out_ends_the_session(sign_in, client):
    fan = sign_in("lejie")
    assert client.post("/api/logout", headers=fan.headers).status_code == 204
    assert client.get("/api/hold", headers=fan.headers).status_code == 401
