"""R9: only signed-in fans can use their account."""


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


def test_requests_without_a_token_are_refused(client):
    for method, path in [("get", "/api/seats"), ("get", "/api/hold"), ("get", "/api/tickets"),
                         ("post", "/api/hold/seats"), ("delete", "/api/hold")]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "not_signed_in"


def test_a_made_up_token_is_refused(client):
    response = client.get("/api/hold", headers={"Authorization": "Bearer made-up"})
    assert response.status_code == 401


def test_signing_out_ends_the_session(sign_in, client):
    fan = sign_in("lejie")
    assert client.post("/api/logout", headers=fan.headers).status_code == 204
    assert client.get("/api/hold", headers=fan.headers).status_code == 401
