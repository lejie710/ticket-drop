"""A crowd of fans at the sale opening (R14).

Each simulated fan signs in with its own sample account, looks at the seat
map, tries to hold seats that looked free, and pays. A 409 answer (seat
taken, limit reached, sale not open) is the system working correctly, so it
counts as a success. Only server errors and broken connections are failures.
"""

import itertools
import random
import threading
import uuid

from locust import HttpUser, between, task

_numbers = itertools.count(1)
_lock = threading.Lock()
EXPECTED = {200, 204, 402, 409, 429}


def next_username() -> str:
    with _lock:
        return f"fan{next(_numbers):03d}"


class Fan(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        r = self.client.post("/api/login", json={"username": next_username(), "password": "demo-pass"}, name="login")
        self.headers = {"Authorization": f"Bearer {r.json()['token']}"}
        self.free = []
        self.held = 0

    def _call(self, method, path, name, **kwargs):
        with self.client.request(method, path, name=name, headers={**self.headers, **kwargs.pop("headers", {})},
                                 catch_response=True, **kwargs) as r:
            if r.status_code in EXPECTED:
                r.success()
            else:
                r.failure(f"unexpected {r.status_code}")
            return r

    @task(4)
    def look_at_seat_map(self):
        r = self._call("GET", "/api/seats", "GET /api/seats")
        if r.status_code == 200:
            self.free = [s["id"] for s in r.json()["seats"] if s["state"] == "available"]

    @task(6)
    def try_to_hold_a_seat(self):
        if not self.free or self.held >= 4:
            return
        # Most fans aim for the front, which is where the contention is.
        seat_id = random.choice(self.free[:120]) if random.random() < 0.7 else random.choice(self.free)
        r = self._call("POST", "/api/hold/seats", "POST /api/hold/seats", json={"seat_id": seat_id})
        if r.status_code == 200:
            self.held = len(r.json()["hold"]["seats"])

    @task(2)
    def pay(self):
        if not self.held:
            return
        card = "4242424242424242" if random.random() < 0.8 else "4000000000000002"
        r = self._call("POST", "/api/checkout", "POST /api/checkout", json={"card_number": card},
                       headers={"Idempotency-Key": uuid.uuid4().hex})
        if r.status_code == 200:
            self.held = 0
