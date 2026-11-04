"""Run the sale-opening spike with Locust, then check the database for damage.

    .venv\\Scripts\\python.exe tools\\run_load_test.py [--users 200] [--seconds 60]

The server starts on a fresh database with the sale opening a few seconds
later, so the crowd arrives before the opening and hits it all at once.
Results go to evidence/load/. Latency figures describe this laptop on this
run; they are observations, not a service level.
"""

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import live_server  # noqa: E402

OUT = ROOT / "evidence" / "load"


def integrity(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    checks = {
        "tickets_issued": one("SELECT COUNT(*) FROM tickets"),
        "seats_sold_twice": one("SELECT COUNT(*) FROM (SELECT seat_id FROM tickets GROUP BY seat_id HAVING COUNT(*) > 1)"),
        "sold_seats_without_ticket": one("SELECT COUNT(*) FROM seats WHERE status = 'sold' AND id NOT IN (SELECT seat_id FROM tickets)"),
        "tickets_on_unsold_seats": one("SELECT COUNT(*) FROM tickets t JOIN seats s ON s.id = t.seat_id WHERE s.status != 'sold'"),
        "accounts_over_limit": one("SELECT COUNT(*) FROM (SELECT user_id FROM tickets GROUP BY user_id HAVING COUNT(*) > 4)"),
        "charged_cents": one("SELECT COALESCE(SUM(amount_cents), 0) FROM charges"),
        "ticket_value_cents": one("SELECT COALESCE(SUM(s.price_cents), 0) FROM tickets t JOIN seats s ON s.id = t.seat_id"),
        "payments_left_pending": one("SELECT COUNT(*) FROM payments WHERE outcome = 'pending'"),
    }
    conn.close()
    checks["money_matches_tickets"] = checks["charged_cents"] == checks["ticket_value_cents"]
    checks["passed"] = (checks["seats_sold_twice"] == 0 and checks["sold_seats_without_ticket"] == 0
                        and checks["tickets_on_unsold_seats"] == 0 and checks["accounts_over_limit"] == 0
                        and checks["money_matches_tickets"] and checks["payments_left_pending"] == 0)
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    work = ROOT / ".local" / "load"
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / f"load-{int(time.time())}.db"
    server = live_server.start(str(db_path), sale_opens_in=5)
    try:
        cmd = [sys.executable, "-m", "locust", "-f", "load/locustfile.py", "--headless",
               "--host", server.url, "-u", str(args.users), "-r", str(args.users),
               "-t", f"{args.seconds}s", "--csv", str(work / "spike"), "--only-summary", "--loglevel", "WARNING"]
        started = time.time()
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=args.seconds + 120)
        elapsed = time.time() - started
    finally:
        live_server.stop(server)

    with open(work / "spike_stats.csv", newline="", encoding="utf-8") as f:
        stats = list(csv.DictReader(f))
    endpoints = []
    for row in stats:
        endpoints.append({
            "name": row["Name"], "requests": int(row["Request Count"]), "failures": int(row["Failure Count"]),
            "median_ms": float(row["Median Response Time"]), "p95_ms": float(row["95%"]),
            "p99_ms": float(row["99%"]), "max_ms": float(row["Max Response Time"]),
            # Locust's own Requests/s column is the rate near the end of the run, so compute the average.
            "rps": round(int(row["Request Count"]) / args.seconds, 1),
        })
    checks = integrity(str(db_path))
    summary = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "users": args.users, "spawn_rate_per_second": args.users, "duration_seconds": args.seconds,
        "wall_seconds": round(elapsed, 1), "locust_exit_code": run.returncode,
        "endpoints": endpoints, "integrity": checks,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    total = next(e for e in endpoints if e["name"] == "Aggregated")
    lines = [
        "# Sale-opening spike",
        "",
        f"{args.users} simulated fans, all started within one second, for {args.seconds} seconds, "
        f"against one local server process on the development laptop. Run at {summary['run_at']}.",
        "",
        "| Endpoint | Requests | Failures | Median ms | p95 ms | p99 ms | Max ms | Avg req/s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in endpoints:
        lines.append(f"| {e['name']} | {e['requests']} | {e['failures']} | {e['median_ms']:.0f} | {e['p95_ms']:.0f} "
                     f"| {e['p99_ms']:.0f} | {e['max_ms']:.0f} | {e['rps']} |")
    lines += [
        "",
        "Failures count only server errors and broken connections. Refusals such as seat taken or limit reached are correct answers.",
        "",
        "## Database checked after the run",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, value in checks.items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += ["", f"Overall: {'PASS' if checks['passed'] and total['failures'] == 0 else 'FAIL'}"]
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if checks["passed"] and total["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
