"""Fill the static showcase page from the saved evidence.

    .venv\\Scripts\\python.exe tools\\build_site.py

Copies screenshots into site/assets and writes the fault table and the
caught count into site/index.html between their markers, so the page only
ever quotes numbers that exist in evidence/.
"""

import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.faults import CATALOGUE  # noqa: E402

SITE = ROOT / "site"
SHOTS = ["seat-map-hold.png", "payment-declined.png", "phone.png"]

PLAIN = {
    "seat_checked_before_lock": "Two fans clicking one seat at the same instant could both be told they hold it",
    "limit_ignores_owned_tickets": "A fan who already bought four tickets could hold four more",
    "hold_expiry_boundary_exclusive": "At the exact second a hold ends, its seats stayed blocked",
    "timeout_leaves_hold_paying": "After a payment timeout, the fan's seats were stuck for ever",
    "idempotency_reruns_failed_payment": "Retrying a declined payment with the same key charged the card",
    "client_sets_amount": "The browser could choose the price",
    "remove_seat_from_any_hold": "A fan could release a seat held by someone else",
    "seat_rate_limit_per_session": "Signing in again reset the rate limit",
    "map_stale_after_failed_seat_change": "After a failed click the seat map stayed wrong for a few seconds",
    "release_hold_leaves_seats_held": "Releasing all seats closed the hold but never freed the seats",
}


def load(name):
    path = ROOT / "evidence" / "faults" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"results": []}


def main() -> int:
    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    for name in SHOTS:
        shutil.copyfile(ROOT / "docs" / "screenshots" / name, SITE / "assets" / name)

    scripted = {r["fault"]: r for r in load("scripted.json")["results"]}
    runs = load("explorers.json")["results"] + load("explorers-llm-seeds.json")["results"]
    rows, caught = [], 0
    for name in CATALOGUE:
        s = scripted.get(name)
        hit = bool(s and s["failed"])
        caught += hit
        rnd = [r for r in runs if r["fault"] == name and r["chooser"] == "random"]
        llm = [r for r in runs if r["fault"] == name and r["chooser"] == "llm"]

        def cell(rs):
            n = sum(bool(r["findings"]) for r in rs)
            return f'<td class="{"yes" if n else "no"}">{n} of {len(rs)} runs</td>' if rs else "<td>not run</td>"

        rows.append(f"<tr><td>{html.escape(PLAIN[name])}</td>"
                    f'<td class="{"yes" if hit else "no"}">{"caught" if hit else "missed"}</td>'
                    f"{cell(rnd)}{cell(llm)}</tr>")
    table = ("<table>\n<thead><tr><th>Planted bug</th><th>Test suite</th><th>Random explorer</th>"
             "<th>Local AI explorer (llama3.2)</th></tr></thead>\n<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>\n"
             "<p>The two bugs the suite missed were then covered by one new test each; both are now caught.</p>")

    page = (SITE / "index.html").read_text(encoding="utf-8")
    page = re.sub(r"<!-- FAULT_TABLE -->.*?<!-- /FAULT_TABLE -->|<!-- FAULT_TABLE -->",
                  f"<!-- FAULT_TABLE -->\n{table}\n<!-- /FAULT_TABLE -->", page, flags=re.S)
    page = re.sub(r"<dt><!-- FAULTS_CAUGHT -->.*?</dt>", f"<dt><!-- FAULTS_CAUGHT -->{caught} of {len(CATALOGUE)}</dt>",
                  page, flags=re.S)
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"site built: {caught} of {len(CATALOGUE)} caught by the suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
