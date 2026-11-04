"""R2, R3, R7 under real parallel requests against a live server.

A threading.Barrier releases every request at the same instant, which is
the situation a sale opening creates. The database is then read directly,
because a correct-looking set of HTTP answers is not proof of a correct
final state.
"""

import random
import sqlite3
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.concurrency

SUCCESS = "4242424242424242"


def run_together(tasks):
    """Run callables in parallel, all starting at the same moment."""
    barrier = threading.Barrier(len(tasks))

    def wrapped(task):
        barrier.wait()
        return task()

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        return list(pool.map(wrapped, tasks))


def rows(db_path, sql, *params):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def sign_in_many(server, count, start=1):
    return [server.login(f"fan{i:03d}") for i in range(start, start + count)]


def test_fifty_fans_press_the_same_seat_at_once(server):
    fans = sign_in_many(server, 50)

    def attempt(headers):
        return lambda: server.http.post("/api/hold/seats", json={"seat_id": "A-08"}, headers=headers)

    responses = run_together([attempt(h) for h in fans])
    codes = Counter(r.status_code for r in responses)
    assert codes == {200: 1, 409: 49}, codes
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {"seat_taken"}
    holders = rows(server.db_path, "SELECT COUNT(*) FROM seats WHERE id = 'A-08' AND status = 'held'")
    assert holders == [(1,)]


def test_one_fan_cannot_beat_the_limit_with_parallel_requests(server):
    headers = server.login("fan100")
    seats = [f"J-{n:02d}" for n in range(1, 11)]

    def attempt(seat_id):
        return lambda: server.http.post("/api/hold/seats", json={"seat_id": seat_id}, headers=headers)

    responses = run_together([attempt(s) for s in seats])
    codes = Counter(r.status_code for r in responses)
    assert codes[200] == 4, codes
    assert codes[200] + codes[409] == 10  # No server errors.
    held = rows(server.db_path, "SELECT COUNT(*) FROM seats WHERE status = 'held'")
    assert held == [(4,)]


def test_double_clicking_pay_charges_once(server):
    headers = server.login("fan200")
    server.http.post("/api/hold/seats", json={"seat_id": "K-05"}, headers=headers).raise_for_status()

    def pay():
        return server.http.post("/api/checkout", json={"card_number": SUCCESS},
                          headers={**headers, "Idempotency-Key": uuid.uuid4().hex})

    responses = run_together([pay for _ in range(5)])
    codes = Counter(r.status_code for r in responses)
    assert codes[200] == 1, codes
    assert codes[200] + codes[409] == 5
    assert rows(server.db_path, "SELECT COUNT(*) FROM charges") == [(1,)]
    assert rows(server.db_path, "SELECT COUNT(*) FROM tickets") == [(1,)]


def test_parallel_retries_with_one_key_charge_once(server):
    headers = server.login("fan201")
    server.http.post("/api/hold/seats", json={"seat_id": "K-06"}, headers=headers).raise_for_status()
    key = "retry-" + uuid.uuid4().hex

    def pay():
        return server.http.post("/api/checkout", json={"card_number": SUCCESS},
                          headers={**headers, "Idempotency-Key": key})

    responses = run_together([pay for _ in range(5)])
    assert all(r.status_code in (200, 409) for r in responses)
    assert rows(server.db_path, "SELECT COUNT(*) FROM charges") == [(1,)]
    # Once the first attempt has finished, the same key returns its stored result.
    again = pay()
    assert again.status_code == 200
    assert again.json()["payment"]["id"] == rows(server.db_path, "SELECT payment_id FROM charges")[0][0]


def test_crowd_on_a_few_hot_seats_never_double_sells(server):
    """60 fans each try to grab 4 of 20 front-row seats, then everyone who holds seats pays."""
    rng = random.Random(7)
    hot = [f"A-{n:02d}" for n in range(1, 17)] + ["B-01", "B-02", "B-03", "B-04"]
    fans = sign_in_many(server, 60, start=300)
    picks = [rng.sample(hot, 4) for _ in fans]

    def grab(headers, seats):
        def go():
            results = []
            for seat_id in seats:
                r = server.http.post("/api/hold/seats", json={"seat_id": seat_id}, headers=headers)
                results.append(r.status_code)
            pay = server.http.post("/api/checkout", json={"card_number": SUCCESS},
                             headers={**headers, "Idempotency-Key": uuid.uuid4().hex})
            return results + [pay.status_code]
        return go

    outcomes = run_together([grab(h, s) for h, s in zip(fans, picks)])
    all_codes = Counter(code for result in outcomes for code in result)
    assert all(code < 500 for code in all_codes), all_codes

    sold = rows(server.db_path, "SELECT seat_id FROM tickets")
    assert len(sold) >= 1, "nothing was sold, so the checks below would prove nothing"
    assert len(sold) == len({s for (s,) in sold}), "a seat was sold twice"
    assert len(sold) <= len(hot)
    paid = sum(1 for result in outcomes if result[-1] == 200)
    charged_payments = rows(server.db_path, "SELECT COUNT(DISTINCT payment_id) FROM charges")[0][0]
    assert paid == charged_payments, "every successful checkout is one charged payment, and no other"
    per_user = rows(server.db_path, "SELECT user_id, COUNT(*) FROM tickets GROUP BY user_id")
    assert all(n <= 4 for _, n in per_user)
    charged = rows(server.db_path, "SELECT COALESCE(SUM(amount_cents), 0) FROM charges")[0][0]
    ticket_value = rows(server.db_path,
                        "SELECT COALESCE(SUM(s.price_cents), 0) FROM tickets t JOIN seats s ON s.id = t.seat_id")[0][0]
    assert charged == ticket_value, "money charged does not match tickets issued"
