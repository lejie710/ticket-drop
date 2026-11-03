"""Run the scripted test suite once per seeded fault and record what it caught.

    .venv\\Scripts\\python.exe tools\\fault_matrix.py [--only name1,name2]

A fault counts as caught when at least one test fails with it enabled while
the same suite passes on the clean application. Results go to
evidence/faults/scripted.json. Takes roughly three minutes per fault.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.faults import CATALOGUE  # noqa: E402

OUT = ROOT / "evidence" / "faults"
SUITE = ["tests/api", "tests/security", "tests/concurrency", "tests/e2e"]


def run_suite(fault: str) -> dict:
    report = ROOT / ".local" / f"junit-{fault or 'clean'}.xml"
    env = {**os.environ, "TICKET_DROP_FAULTS": fault}
    started = time.time()
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "--tb=no", "-p", "no:cacheprovider",
                           f"--junitxml={report}"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
    failed = []
    total = 0
    for case in ET.parse(report).getroot().iter("testcase"):
        total += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname').split('.')[-1]}::{case.get('name')}")
    return {"fault": fault or "clean", "tests": total, "failed": failed, "seconds": round(time.time() - started),
            "exit_code": proc.returncode}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="Comma-separated fault names. Default: all.")
    parser.add_argument("--out", default="scripted.json", help="Result file name in evidence/faults.")
    args = parser.parse_args()
    names = [n for n in args.only.split(",") if n] or list(CATALOGUE)
    OUT.mkdir(parents=True, exist_ok=True)
    results = [run_suite("")]
    print(f"clean: {len(results[0]['failed'])} failures of {results[0]['tests']}", flush=True)
    for name in names:
        result = run_suite(name)
        results.append(result)
        print(f"{name}: {'CAUGHT' if result['failed'] else 'missed'} by {len(result['failed'])} test(s) "
              f"in {result['seconds']} s", flush=True)
    (OUT / args.out).write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "suite": SUITE, "results": results,
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
