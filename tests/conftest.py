"""Shared fixtures. Each test gets a fresh database file and a frozen clock."""

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import payments
from app.clock import Clock
from app.config import Settings
from app.main import create_app

T0 = 1_800_000_000_000  # A fixed instant, so time rules are exact.
SUCCESS = payments.SUCCESS_CARD
DECLINE = payments.DECLINE_CARD
TIMEOUT = payments.TIMEOUT_CARD


def pytest_configure(config):
    # --basetemp points inside .local, which a fresh clone does not have yet.
    Path(__file__).resolve().parent.parent.joinpath(".local").mkdir(exist_ok=True)


class Fan:
    """One signed-in account, with the calls a fan makes."""

    def __init__(self, client: TestClient, token: str, username: str):
        self.client = client
        self.username = username
        self.headers = {"Authorization": f"Bearer {token}"}

    def hold(self, seat_id):
        return self.client.post("/api/hold/seats", json={"seat_id": seat_id}, headers=self.headers)

    def unhold(self, seat_id):
        return self.client.delete(f"/api/hold/seats/{seat_id}", headers=self.headers)

    def release_all(self):
        return self.client.delete("/api/hold", headers=self.headers)

    def current_hold(self):
        return self.client.get("/api/hold", headers=self.headers).json()["hold"]

    def checkout(self, card=SUCCESS, key=None):
        key = key or uuid.uuid4().hex
        return self.client.post("/api/checkout", json={"card_number": card},
                                headers={**self.headers, "Idempotency-Key": key})

    def seat_states(self):
        seats = self.client.get("/api/seats", headers=self.headers).json()["seats"]
        return {s["id"]: s["state"] for s in seats}

    def tickets(self):
        return self.client.get("/api/tickets", headers=self.headers).json()["tickets"]


@pytest.fixture
def clock():
    return Clock(frozen_at_ms=T0)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def make_client(db_path, clock):
    def make(**overrides):
        settings = Settings(db_path=db_path, payment_timeout_seconds=0, **overrides)
        return TestClient(create_app(settings, clock))
    return make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def sign_in(client):
    def _sign_in(username="mei", c=None):
        c = c or client
        response = c.post("/api/login", json={"username": username, "password": "demo-pass"})
        assert response.status_code == 200, response.text
        return Fan(c, response.json()["token"], username)
    return _sign_in


@pytest.fixture
def query(db_path):
    """Read the database directly, to check what really happened behind the API."""
    def _query(sql, *params):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()
    return _query
