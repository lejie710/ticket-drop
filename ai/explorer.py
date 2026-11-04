"""An exploratory tester driven by a language model, and a random baseline.

Both explorers act through the same small set of actions against a live
server, and the same rule checks (oracles) run after every action. The only
difference is who chooses the next action: the local model, reasoning from
the product rules and what it has seen, or a random number generator. That
separates "the checks found a bug" from "the chooser led the checks to it".

The checks were written from the requirements in docs/BRIEF.md before the
seeded-fault catalogue existed, and were not changed afterwards.
"""

import json
import random
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from tests.support.live_server import LiveServer

ACTORS = {"A": "lejie", "B": "arjun", "C": "siti"}
CARDS = {"success": "4242424242424242", "decline": "4000000000000002", "timeout": "4000000000000408"}
FRONT_SEATS = [f"{r}-{n:02d}" for r in "ABCD" for n in range(1, 11)]
HOLD_MS = 300_000

RULES = """Ticket Drop sells seats for one concert. Rules:
- The sale opens 60 seconds after the server starts. Before that, holding seats must be refused.
- A seat can be held or sold by only one account at a time, even when many people click at once.
- An account may hold and own at most 4 seats in total.
- A hold lasts exactly 300 seconds from the first seat. At 300 seconds the seats return to sale.
- Paying with card 'success' issues one ticket per held seat. 'decline' and 'timeout' charge nothing,
  issue nothing, and the seats stay held so the fan can retry.
- Repeating a checkout with the same key must not charge again and must return the first result.
- The price is decided by the server.
- One account can never see or change another account's holds or tickets.
- Rapid repeated seat changes from one account are rate limited.
- The seat map must show each seat as available, taken or mine, matching reality."""

ACTIONS = """Actions (reply with exactly one, as JSON):
{"action": "seat_map", "as": "A"}                      see what account A sees
{"action": "hold", "as": "A", "seat": "C-09"}          hold one seat
{"action": "hold_many", "as": "A", "seats": ["C-01", "C-02"]}
{"action": "unhold", "as": "B", "seat": "C-09"}        release one seat (try other accounts' seats too)
{"action": "release_all", "as": "A"}
{"action": "checkout", "as": "A", "card": "success", "key": "k1"}   card: success, decline or timeout
{"action": "my_tickets", "as": "A"}
{"action": "get_ticket", "as": "B", "ticket_of": "A"}  try to read another account's ticket
{"action": "crowd_hold", "seat": "C-09", "fans": 10}   many new fans press one seat at the same instant
{"action": "double_pay", "as": "A", "times": 3}        press Pay several times at once
{"action": "rapid_changes", "as": "A", "seat": "C-09", "times": 15}
{"action": "wait", "seconds": 60}                      move the server clock forward
Accounts: A, B, C. Seats look like C-09: row A to T, two-digit number."""


@dataclass
class Finding:
    step: int
    rule: str
    detail: str


@dataclass
class Harness:
    server: LiveServer
    sale_opens_at_ms: int
    headers: dict = field(default_factory=dict)
    tickets: dict = field(default_factory=dict)
    fan_counter: int = 0
    findings: list = field(default_factory=list)
    step: int = 0

    def h(self, actor: str) -> dict:
        if actor not in self.headers:
            self.headers[actor] = self.server.login(ACTORS[actor])
        return self.headers[actor]

    def db(self, sql, *params):
        conn = sqlite3.connect(self.server.db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def server_now(self) -> int:
        return self.server.http.get("/api/event").json()["server_now_ms"]

    def flag(self, rule: str, detail: str):
        self.findings.append(Finding(self.step, rule, detail))

    def user_id(self, actor: str) -> int:
        return self.db("SELECT id FROM users WHERE username = ?", ACTORS[actor])[0][0]

    # ---------- actions ----------

    def run(self, act: dict) -> dict:
        kind = act.get("action")
        actor = act.get("as", "A") if act.get("as") in ACTORS else "A"
        http = self.server.http
        if kind == "seat_map":
            r = http.get("/api/seats", headers=self.h(actor))
            self.check_status(r)
            if r.status_code == 200:
                self.check_map(actor, r.json()["seats"])
                seats = r.json()["seats"]
                free = [s["id"] for s in seats if s["state"] == "available"][:6]
                mine = [s["id"] for s in seats if s["state"] == "mine"]
                return {"status": 200, "available_count": sum(s["state"] == "available" for s in seats),
                        "some_available": free, "mine": mine}
            return self.brief(r)
        if kind == "hold":
            return self.hold(actor, str(act.get("seat", "")))
        if kind == "hold_many":
            return {"results": [self.hold(actor, str(s)) for s in list(act.get("seats", []))[:6]]}
        if kind == "unhold":
            seat = str(act.get("seat", ""))
            owner = self.db("SELECT h.user_id FROM seats s JOIN holds h ON h.id = s.hold_id WHERE s.id = ?", seat)
            r = http.delete(f"/api/hold/seats/{seat}", headers=self.h(actor))
            self.check_status(r)
            if r.status_code == 200 and owner and owner[0][0] != self.user_id(actor):
                self.flag("R9", f"{actor} released seat {seat}, which was held by another account")
            return self.brief(r)
        if kind == "release_all":
            r = http.delete("/api/hold", headers=self.h(actor))
            self.check_status(r)
            return self.brief(r)
        if kind == "checkout":
            return self.checkout(actor, str(act.get("card", "success")), str(act.get("key", "k1")))
        if kind == "my_tickets":
            r = http.get("/api/tickets", headers=self.h(actor))
            self.check_status(r)
            if r.status_code == 200:
                self.tickets[actor] = [t["id"] for t in r.json()["tickets"]]
                return {"status": 200, "tickets": [t["seat_id"] for t in r.json()["tickets"]]}
            return self.brief(r)
        if kind == "get_ticket":
            owner = act.get("ticket_of", "A") if act.get("ticket_of") in ACTORS else "A"
            ids = [r[0] for r in self.db("SELECT id FROM tickets WHERE user_id = ?", self.user_id(owner))]
            if not ids:
                return {"note": f"{owner} has no tickets yet"}
            r = http.get(f"/api/tickets/{ids[0]}", headers=self.h(actor))
            self.check_status(r)
            if r.status_code == 200 and owner != actor:
                self.flag("R9", f"{actor} could read a ticket belonging to {owner}")
            return self.brief(r)
        if kind == "crowd_hold":
            return self.crowd_hold(str(act.get("seat", "")), max(2, min(int(act.get("fans", 10) or 10), 20)))
        if kind == "double_pay":
            return self.double_pay(actor, max(2, min(int(act.get("times", 3) or 3), 6)))
        if kind == "rapid_changes":
            return self.rapid(actor, str(act.get("seat", "")), max(2, min(int(act.get("times", 15) or 15), 30)))
        if kind == "wait":
            seconds = max(1, min(int(act.get("seconds", 60) or 60), 900))
            self.server.advance_clock(seconds * 1000)
            return self.after_wait(seconds)
        return {"error": f"unknown action {kind!r}"}

    def hold(self, actor, seat):
        before_open = self.server_now() < self.sale_opens_at_ms
        r = self.server.http.post("/api/hold/seats", json={"seat_id": seat}, headers=self.h(actor))
        self.check_status(r)
        if r.status_code == 200 and before_open:
            self.flag("R1", f"{actor} held {seat} before the sale opened")
        return self.brief(r)

    def checkout(self, actor, card_name, key_label):
        card = CARDS.get(card_name, card_name)
        key = f"{actor}-{key_label}"[:64]
        if len(key) < 8:
            key = key + "-explore"
        held_before = {r[0] for r in self.db(
            "SELECT s.id FROM seats s JOIN holds h ON h.id = s.hold_id WHERE h.user_id = ?", self.user_id(actor))}
        previous = self.db("SELECT response_status, response_body FROM payments WHERE user_id = ? AND idempotency_key = ?",
                           self.user_id(actor), key)
        r = self.server.http.post("/api/checkout", json={"card_number": card},
                                  headers={**self.h(actor), "Idempotency-Key": key})
        self.check_status(r)
        if previous and previous[0][0] is not None:
            if r.status_code != previous[0][0] or r.json() != json.loads(previous[0][1]):
                self.flag("R7", f"repeating key {key_label} gave a different result ({previous[0][0]} then {r.status_code})")
        elif r.status_code in (402, 504) and held_before:
            still = {row[0] for row in self.db(
                "SELECT s.id FROM seats s JOIN holds h ON h.id = s.hold_id WHERE h.user_id = ? AND h.status = 'active'",
                self.user_id(actor))}
            if not held_before <= still and self.server_now() < self.hold_expiry(actor, default=10**15):
                self.flag("R6", f"after a {card_name} the seats {sorted(held_before - still)} were no longer held")
        return self.brief(r)

    def hold_expiry(self, actor, default):
        rows = self.db("SELECT expires_ms FROM holds WHERE user_id = ? ORDER BY created_ms DESC LIMIT 1", self.user_id(actor))
        return rows[0][0] if rows else default

    def crowd_hold(self, seat, fans):
        crowd = []
        for _ in range(fans):
            self.fan_counter += 1
            crowd.append(self.server.login(f"fan{self.fan_counter:03d}"))
        barrier = threading.Barrier(fans)

        def go(headers):
            barrier.wait()
            return self.server.http.post("/api/hold/seats", json={"seat_id": seat}, headers=headers)

        with ThreadPoolExecutor(fans) as pool:
            results = list(pool.map(go, crowd))
        for r in results:
            self.check_status(r)
        wins = sum(r.status_code == 200 for r in results)
        if wins > 1:
            self.flag("R2", f"{wins} fans were all told they hold seat {seat}")
        return {"fans": fans, "succeeded": wins, "codes": sorted({r.status_code for r in results})}

    def double_pay(self, actor, times):
        barrier = threading.Barrier(times)

        def go(_):
            barrier.wait()
            return self.server.http.post("/api/checkout", json={"card_number": CARDS["success"]},
                                         headers={**self.h(actor), "Idempotency-Key": uuid.uuid4().hex})

        with ThreadPoolExecutor(times) as pool:
            results = list(pool.map(go, range(times)))
        for r in results:
            self.check_status(r)
        return {"times": times, "codes": [r.status_code for r in results]}

    def rapid(self, actor, seat, times):
        codes = []
        for i in range(times):
            if i % 2 == 0:
                r = self.server.http.post("/api/hold/seats", json={"seat_id": seat}, headers=self.h(actor))
            else:
                r = self.server.http.delete(f"/api/hold/seats/{seat}", headers=self.h(actor))
            self.check_status(r)
            codes.append(r.status_code)
        if times >= 12 and 429 not in codes and codes.count(200) >= 12:
            self.flag("R10", f"{times} rapid seat changes by {actor} were never rate limited")
        return {"codes": codes}

    def after_wait(self, seconds):
        # Any read triggers expiry of overdue holds; then nothing overdue may remain open.
        for actor in self.headers:
            self.check_status(self.server.http.get("/api/hold", headers=self.headers[actor]))
        now = self.server_now()
        overdue = self.db("SELECT COUNT(*) FROM holds WHERE status = 'active' AND expires_ms <= ?", now)[0][0]
        if overdue:
            self.flag("R4", f"{overdue} hold(s) still active at or after their expiry time")
        return {"waited_seconds": seconds, "sale_open": now >= self.sale_opens_at_ms}

    # ---------- checks ----------

    def check_status(self, r):
        if r.status_code >= 500 and r.status_code != 504:
            self.flag("R12", f"server error {r.status_code} on {r.request.method} {r.request.url.path}")

    def check_map(self, actor, seats):
        uid = self.user_id(actor)
        truth = {}
        for sid, status, holder in self.db(
                "SELECT s.id, s.status, h.user_id FROM seats s LEFT JOIN holds h ON h.id = s.hold_id"):
            truth[sid] = ("mine" if holder == uid else "taken") if status == "held" else status
        for sid, owner in self.db("SELECT seat_id, user_id FROM tickets"):
            truth[sid] = "mine" if owner == uid else "taken"
        for sid in truth:
            if truth[sid] == "sold":
                truth[sid] = "taken"
        wrong = [s["id"] for s in seats if truth.get(s["id"]) != s["state"]]
        if wrong:
            self.flag("R11", f"seat map for {actor} shows {len(wrong)} seat(s) wrongly, e.g. {wrong[:3]}")

    def check_invariants(self):
        db = self.db
        twice = db("SELECT COUNT(*) FROM (SELECT seat_id FROM tickets GROUP BY seat_id HAVING COUNT(*) > 1)")[0][0]
        if twice:
            self.flag("R2", f"{twice} seat(s) sold twice")
        over = db("""SELECT u.username, (SELECT COUNT(*) FROM tickets t WHERE t.user_id = u.id)
                     + (SELECT COUNT(*) FROM seats s JOIN holds h ON h.id = s.hold_id
                        WHERE h.user_id = u.id AND h.status IN ('active', 'paying')) AS n
                     FROM users u WHERE u.username IN ('lejie', 'arjun', 'siti') AND n > 4""")
        for name, n in over:
            self.flag("R3", f"{name} has {n} seats held or owned")
        charged = db("SELECT COALESCE(SUM(amount_cents), 0) FROM charges")[0][0]
        value = db("SELECT COALESCE(SUM(s.price_cents), 0) FROM tickets t JOIN seats s ON s.id = t.seat_id")[0][0]
        if charged != value:
            self.flag("R5/R8", f"charged {charged} cents but tickets are worth {value} cents")
        stale = db("""SELECT COUNT(*) FROM seats s JOIN holds h ON h.id = s.hold_id
                      WHERE s.status = 'held' AND h.status NOT IN ('active', 'paying')""")[0][0]
        if stale:
            self.flag("R13", f"{stale} seat(s) still held under a closed hold")

    @staticmethod
    def brief(r) -> dict:
        try:
            body = r.json()
        except ValueError:
            body = None
        out = {"status": r.status_code}
        if isinstance(body, dict):
            if "error" in body:
                out["error"] = body["error"].get("code")
            if body.get("hold") is not None:
                out["held"] = [s["id"] for s in body["hold"]["seats"]]
            if "tickets" in body:
                out["tickets"] = len(body["tickets"])
        return out


# ---------- choosers ----------

class RandomChooser:
    name = "random"

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def next_action(self, history) -> dict:
        r = self.rng
        actor = r.choice(list(ACTORS))
        seat = r.choice(FRONT_SEATS)
        kind = r.choice(["seat_map", "hold", "hold_many", "unhold", "release_all", "checkout", "my_tickets",
                         "get_ticket", "crowd_hold", "double_pay", "rapid_changes", "wait"])
        return {
            "seat_map": {"action": kind, "as": actor},
            "hold": {"action": kind, "as": actor, "seat": seat},
            "hold_many": {"action": kind, "as": actor, "seats": r.sample(FRONT_SEATS, r.randint(2, 6))},
            "unhold": {"action": kind, "as": actor, "seat": seat},
            "release_all": {"action": kind, "as": actor},
            "checkout": {"action": kind, "as": actor, "card": r.choice(list(CARDS)), "key": r.choice(["k1", "k2", "k3"])},
            "my_tickets": {"action": kind, "as": actor},
            "get_ticket": {"action": kind, "as": actor, "ticket_of": r.choice(list(ACTORS))},
            "crowd_hold": {"action": kind, "seat": seat, "fans": r.randint(2, 15)},
            "double_pay": {"action": kind, "as": actor, "times": r.randint(2, 5)},
            "rapid_changes": {"action": kind, "as": actor, "seat": seat, "times": r.randint(2, 20)},
            "wait": {"action": kind, "seconds": r.randint(1, 600)},
        }[kind]


class ModelChooser:
    name = "llm"

    def __init__(self, provider):
        self.provider = provider
        self.invalid_replies = 0

    def next_action(self, history) -> dict:
        recent = "\n".join(f"{i}. {json.dumps(a)} -> {json.dumps(o)[:220]}" for i, (a, o) in enumerate(history[-8:], 1))
        messages = [
            {"role": "system", "content": "You are an exploratory software tester trying to make this application "
                                          "break its rules. Think about edge cases, exact time boundaries, other "
                                          "accounts, failures and many users at once. Do not repeat the same action.\n\n"
                                          + RULES + "\n\n" + ACTIONS},
            {"role": "user", "content": f"Step {len(history) + 1}. Your recent actions and what happened:\n"
                                        f"{recent or '(none yet)'}\n\nChoose the next action. Reply as JSON with the "
                                        "action fields and a short \"why\"."},
        ]
        try:
            act = self.provider.chat(messages, max_tokens=160)
        except Exception as exc:  # A bad reply wastes the step, as it would for a real agent.
            self.invalid_replies += 1
            return {"action": "invalid", "error": str(exc)[:120]}
        if not isinstance(act, dict) or "action" not in act:
            self.invalid_replies += 1
            return {"action": "invalid", "reply": str(act)[:120]}
        return act


def explore(server: LiveServer, chooser, steps: int, sale_opens_at_ms: int, transcript: list | None = None) -> list:
    harness = Harness(server, sale_opens_at_ms)
    history = []
    for step in range(1, steps + 1):
        harness.step = step
        act = chooser.next_action(history)
        try:
            outcome = harness.run(act) if act.get("action") != "invalid" else {"error": "invalid reply"}
        except Exception as exc:  # A malformed action must not stop the run.
            outcome = {"error": f"{type(exc).__name__}: {str(exc)[:100]}"}
        harness.check_invariants()
        history.append((act, outcome))
        if transcript is not None:
            transcript.append({"step": step, "action": act, "outcome": outcome})
    unique = {}
    for f in harness.findings:
        unique.setdefault((f.rule, f.detail.split(",")[0][:60]), f)
    return list(unique.values())
