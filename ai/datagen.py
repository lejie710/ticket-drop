"""Ask the local model for unusual inputs, then judge them with a fixed oracle.

    .venv\\Scripts\\python.exe -m ai.datagen [--per-field 15]

The model's job is only to propose inputs a tester might not think of. It
also labels each one valid or invalid, but that label is never used as the
expected result: the expected result comes from oracle(), written from the
input rules below. Comparing the two measures how well the model understood
the rules. Running every input through the app then shows whether the app
agrees with the oracle.

Writes tests/data/generated_inputs.json (replayed by a normal pytest test,
without the model) and evidence/ai/datagen_report.md.
"""

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ai.provider import ModelError, OllamaProvider
from app.clock import Clock
from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]

FIELDS = {
    "seat_id": "A seat ID: one capital row letter from A to T, a hyphen, then exactly two digits. Example: C-09.",
    "card_number": "A card number: 12 to 23 characters, only digits and spaces.",
    "idempotency_key": "An idempotency key: 8 to 64 characters, only letters, digits, hyphen and underscore.",
    "username": "A username: 1 to 32 characters, only lowercase letters, digits and underscore.",
}

ORACLE = {
    "seat_id": re.compile(r"[A-T]-\d{2}"),
    "card_number": re.compile(r"[0-9 ]{12,23}"),
    "idempotency_key": re.compile(r"[A-Za-z0-9_-]{8,64}"),
    "username": re.compile(r"[a-z0-9_]{1,32}"),
}

# What the hand-written tests already cover, to measure novelty.
HAND_WRITTEN = {
    "seat_id": {"Z-01", "c-09", "C-9", "C-009", "C09", "", "C-09'; DROP TABLE seats;--", "C-09\n"},
    "card_number": {"", "abcd", "4242", "4242-4242-4242-4242", "4" * 40},
    "idempotency_key": {"short", "has space here", "x" * 65, "semi;colon!"},
    "username": {"nobody", "lejie"},
}


def oracle(field: str, value) -> bool:
    """True if the value is valid by the written input rules."""
    return isinstance(value, str) and ORACLE[field].fullmatch(value) is not None


PROMPT = """You are a software tester designing input-validation test data.
Rule: {rule}
Propose {n} different test inputs for this field. Mix valid and invalid ones and focus on
edge cases a careless developer might mishandle: exact length limits, off-by-one lengths,
wrong letter case, whitespace, unicode look-alike characters, empty or very long values,
and text shaped like injection attacks.
Reply as JSON: {{"inputs": [{{"value": "...", "valid": true or false, "reason": "..."}}]}}"""


def generate(provider, field: str, n: int) -> list[dict]:
    reply = provider.chat([{"role": "user", "content": PROMPT.format(rule=FIELDS[field], n=n)}], max_tokens=1600)
    items = reply.get("inputs", []) if isinstance(reply, dict) else []
    cleaned = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("value"), str):
            cleaned.append({"value": item["value"], "model_label_valid": bool(item.get("valid")),
                            "model_reason": str(item.get("reason", ""))[:200]})
    return cleaned


def app_accepts(client, headers, field: str, value: str) -> bool:
    """Send the value through the real endpoint and report whether input validation accepted it."""
    if field == "seat_id":
        r = client.post("/api/hold/seats", json={"seat_id": value}, headers=headers)
        if r.status_code == 200:
            client.delete("/api/hold", headers=headers)
        return r.status_code != 422
    if field == "card_number":
        r = client.post("/api/checkout", json={"card_number": value},
                        headers={**headers, "Idempotency-Key": "datagen-card-check"})
        return r.status_code != 422
    if field == "idempotency_key":
        r = client.post("/api/checkout", json={"card_number": "4000000000000002"},
                        headers={**headers, "Idempotency-Key": value})
        return r.status_code != 400
    if field == "username":
        r = client.post("/api/login", json={"username": value, "password": "x"})
        return r.status_code != 422
    raise ValueError(field)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-field", type=int, default=15)
    args = parser.parse_args()
    # Generated inputs include characters the Windows console code page cannot print.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    provider = OllamaProvider(temperature=0.8, seed=11, record_to=ROOT / "evidence" / "ai" / "datagen_transcript.jsonl")
    if not provider.available():
        print("The local model is not available. Start Ollama and run: ollama pull llama3.2")
        return 2

    generated = {}
    for field in FIELDS:
        try:
            generated[field] = generate(provider, field, args.per_field)
        except ModelError as exc:
            print(f"{field}: {exc}")
            generated[field] = []

    with tempfile.TemporaryDirectory() as tmp:
        # Header values must be latin-1 to be sent at all; such keys are recorded as not sendable.
        client = TestClient(create_app(Settings(db_path=str(Path(tmp) / "datagen.db"), payment_timeout_seconds=0,
                                                hold_burst=10_000, hold_rate_per_second=10_000.0), Clock()))
        token = client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        cases, rows = [], []
        for field, items in generated.items():
            seen = set()
            for item in items:
                value = item["value"]
                duplicate = value in seen
                seen.add(value)
                expected_valid = oracle(field, value)
                try:
                    accepted = app_accepts(client, headers, field, value)
                    sendable = True
                except (UnicodeEncodeError, ValueError):
                    accepted, sendable = None, False
                row = {
                    "field": field, "value": value, "expected_valid": expected_valid,
                    "model_label_valid": item["model_label_valid"], "model_reason": item["model_reason"],
                    "duplicate": duplicate, "novel": value not in HAND_WRITTEN[field],
                    "sendable": sendable, "app_accepted": accepted,
                    "app_agrees_with_oracle": None if accepted is None else accepted == expected_valid,
                }
                rows.append(row)
                if not duplicate and sendable:
                    cases.append({"field": field, "value": value, "expected_valid": expected_valid})
            client.post("/api/logout", headers=headers)
            token = client.post("/api/login", json={"username": "lejie", "password": "demo-pass"}).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
        client.close()

    data_file = ROOT / "tests" / "data" / "generated_inputs.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps({
        "provenance": (f"Inputs proposed by {provider.name} via ai/datagen.py on "
                       f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}. expected_valid comes from the "
                       "written input rules (ai.datagen.oracle), not from the model."),
        "cases": cases,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    report = build_report(provider, rows)
    out = ROOT / "evidence" / "ai"
    out.mkdir(parents=True, exist_ok=True)
    (out / "datagen_report.md").write_text(report, encoding="utf-8")
    (out / "datagen_rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(report)
    return 0


def build_report(provider, rows) -> str:
    lines = [
        "# AI-generated input data",
        "",
        f"Model: {provider.name}, {provider.calls} calls, {provider.seconds:.0f} s of model time. "
        f"Run at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "| Field | Proposed | Unique | Novel vs hand-written | Model label correct | Sendable | App agrees with oracle |",
        "|---|---|---|---|---|---|---|",
    ]
    for field in FIELDS:
        fr = [r for r in rows if r["field"] == field]
        unique = [r for r in fr if not r["duplicate"]]
        labelled_right = sum(r["model_label_valid"] == r["expected_valid"] for r in unique)
        sent = [r for r in unique if r["sendable"]]
        agree = sum(bool(r["app_agrees_with_oracle"]) for r in sent)
        lines.append(f"| {field} | {len(fr)} | {len(unique)} | {sum(r['novel'] for r in unique)} | "
                     f"{labelled_right}/{len(unique)} | {len(sent)} | {agree}/{len(sent)} |")
    disagreements = [r for r in rows if r["app_agrees_with_oracle"] is False]
    wrong_labels = [r for r in rows if not r["duplicate"] and r["model_label_valid"] != r["expected_valid"]]
    lines += ["", "## Where the app and the written rules disagree", ""]
    if disagreements:
        for r in disagreements:
            lines.append(f"- {r['field']} `{r['value']!r}`: rules say {'valid' if r['expected_valid'] else 'invalid'}, "
                         f"app {'accepted' if r['app_accepted'] else 'rejected'} it")
    else:
        lines.append("None. Every sendable generated input was accepted or rejected exactly as the rules say.")
    lines += ["", "## Examples where the model labelled its own input wrongly", ""]
    for r in wrong_labels[:12]:
        lines.append(f"- {r['field']} `{r['value']!r}`: model said {'valid' if r['model_label_valid'] else 'invalid'}"
                     f" ({r['model_reason']}); rules say {'valid' if r['expected_valid'] else 'invalid'}")
    if not wrong_labels:
        lines.append("None.")
    lines += ["", "The model label is measured but never used as an expected result. "
              "Accuracy here describes this small local model on this run, not language models in general."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
