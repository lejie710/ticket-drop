"""Run the AI explorer and the random baseline against the clean app and every seeded fault.

    .venv\\Scripts\\python.exe tools\\run_explorers.py [--steps 30] [--random-seeds 3] [--only a,b] [--no-llm]

Each run gets a fresh server and database with the sale opening 60 seconds
after start. Runs on the clean application measure false alarms. Results go
to evidence/faults/explorers.json, and every model decision with its stated
reason goes to evidence/ai/explorer_transcripts.jsonl.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.explorer import ModelChooser, RandomChooser, explore  # noqa: E402
from ai.provider import OllamaProvider  # noqa: E402
from app.faults import CATALOGUE  # noqa: E402
from tests.support import live_server  # noqa: E402

OUT = ROOT / "evidence" / "faults"
TRANSCRIPTS = ROOT / "evidence" / "ai" / "explorer_transcripts.jsonl"


def one_run(fault: str, chooser, steps: int, run_id: int) -> dict:
    db = ROOT / ".local" / "explore" / f"{chooser.name}-{fault or 'clean'}-{run_id}-{int(time.time())}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    server = live_server.start(str(db), faults=fault, sale_opens_in=60)
    transcript = []
    started = time.time()
    try:
        opens_at = server.http.get("/api/event").json()["sale_opens_at_ms"]
        findings = explore(server, chooser, steps, opens_at, transcript)
    finally:
        live_server.stop(server)
    if chooser.name == "llm":
        with TRANSCRIPTS.open("a", encoding="utf-8") as f:
            for row in transcript:
                f.write(json.dumps({"fault": fault or "clean", **row}) + "\n")
    actions = [row["action"].get("action") for row in transcript]
    return {
        "fault": fault or "clean", "chooser": chooser.name, "run": run_id, "steps": steps,
        "seconds": round(time.time() - started),
        "findings": [{"step": f.step, "rule": f.rule, "detail": f.detail} for f in findings],
        "distinct_actions": sorted({a for a in actions if a}),
        "invalid_steps": sum(a == "invalid" for a in actions),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--random-seeds", type=int, default=3)
    parser.add_argument("--only", default="")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--llm-seeds", default="5",
                        help="Comma-separated model seeds, one model run per seed per fault. Default: 5.")
    parser.add_argument("--out", default="explorers.json",
                        help="Result file in evidence/faults. Transcripts are appended to, not replaced, "
                             "unless this is the default file.")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    faults = [""] + ([n for n in args.only.split(",") if n] or list(CATALOGUE))
    seeds = [int(s) for s in args.llm_seeds.split(",") if s]
    providers = []
    if not args.no_llm:
        providers = [OllamaProvider(temperature=0.7, seed=seed) for seed in seeds]
        if not providers[0].available():
            print("The local model is not available; running the random baseline only.")
            providers = []
    TRANSCRIPTS.parent.mkdir(parents=True, exist_ok=True)
    if providers and args.out == "explorers.json":
        TRANSCRIPTS.write_text("", encoding="utf-8")

    results = []
    for fault in faults:
        for seed in range(1, args.random_seeds + 1):
            r = one_run(fault, RandomChooser(seed), args.steps, seed)
            results.append(r)
            print(f"{r['fault']:<38} random#{seed}: {len(r['findings'])} finding(s), {r['seconds']} s", flush=True)
        for provider in providers:
            r = one_run(fault, ModelChooser(provider), args.steps, provider.seed)
            results.append(r)
            print(f"{r['fault']:<38} llm seed {provider.seed}: {len(r['findings'])} finding(s), "
                  f"{r['invalid_steps']} invalid step(s), {r['seconds']} s", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / args.out).write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "steps_per_run": args.steps, "random_seeds": args.random_seeds,
        "model": providers[0].name if providers else None,
        "model_seeds": seeds if providers else [],
        "model_calls": sum(p.calls for p in providers),
        "model_seconds": round(sum(p.seconds for p in providers)),
        "results": results,
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
