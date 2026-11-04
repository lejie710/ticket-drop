"""Combine the saved fault experiments into evidence/faults/REPORT.md.

    .venv\\Scripts\\python.exe tools\\build_reports.py

Reads evidence/faults/scripted.json (tools/fault_matrix.py) and
evidence/faults/explorers.json (tools/run_explorers.py). Runs nothing.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.faults import CATALOGUE  # noqa: E402

OUT = ROOT / "evidence" / "faults"


def load(name):
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def requirement(description: str) -> str:
    import re
    found = re.findall(r"R\d+", description)
    return ", ".join(dict.fromkeys(found)) or "?"


def main() -> int:
    scripted = load("scripted.json")
    explorers = load("explorers.json")
    extra = load("explorers-llm-seeds.json")  # Further model seeds, run separately.
    if explorers and extra:
        explorers = {**explorers, "results": explorers["results"] + extra["results"],
                     "model_calls": explorers["model_calls"] + extra["model_calls"],
                     "model_seconds": explorers["model_seconds"] + extra["model_seconds"],
                     "model_seeds": [5] + extra.get("model_seeds", [])}
    lines = ["# Seeded faults: which approach caught what", ""]
    if not scripted and not explorers:
        print("No results yet. Run tools/fault_matrix.py and tools/run_explorers.py first.")
        return 1

    by_fault = {}
    if scripted:
        for r in scripted["results"]:
            by_fault.setdefault(r["fault"], {})["scripted"] = r
    if explorers:
        for r in explorers["results"]:
            by_fault.setdefault(r["fault"], {}).setdefault(r["chooser"], []).append(r)

    random_runs = explorers["random_seeds"] if explorers else 0
    lines += [
        "Caught means: the scripted suite had at least one failing test, or an explorer run raised at least one finding.",
        f"Random baseline: {random_runs} runs per fault with different seeds; shown as runs that found it.",
        (f"Model explorer: {explorers['model']}, seeds {', '.join(str(x) for x in explorers.get('model_seeds', [5]))}, "
         f"one run per seed per fault; shown as runs that found it. {explorers['steps_per_run']} actions per run."
         if explorers else "Model explorer: not run."),
        "",
        "| Fault | Req | Scripted suite | Random explorer | Model explorer |",
        "|---|---|---|---|---|",
    ]
    totals = {"scripted": 0, "random": 0, "llm": 0}
    for name, description in CATALOGUE.items():
        row = by_fault.get(name, {})
        s = row.get("scripted")
        s_text = "not run" if s is None else (f"caught, {len(s['failed'])} test(s)" if s["failed"] else "missed")
        if s and s["failed"]:
            totals["scripted"] += 1
        rnd = row.get("random", [])
        rnd_hits = sum(bool(r["findings"]) for r in rnd)
        r_text = "not run" if not rnd else f"{rnd_hits}/{len(rnd)} runs"
        if rnd_hits:
            totals["random"] += 1
        llm = row.get("llm", [])
        llm_hits = sum(bool(r["findings"]) for r in llm)
        l_text = "not run" if not llm else f"{llm_hits}/{len(llm)} runs"
        if llm_hits:
            totals["llm"] += 1
        lines.append(f"| `{name}` | {requirement(description)} | {s_text} | {r_text} | {l_text} |")
    n = len(CATALOGUE)
    lines += ["", f"Totals: scripted {totals['scripted']}/{n}, random explorer {totals['random']}/{n} "
              f"(caught in at least one run), model explorer {totals['llm']}/{n} (caught in at least one run).", ""]

    clean = by_fault.get("clean", {})
    lines += ["## False alarms on the clean application", ""]
    if clean.get("scripted"):
        lines.append(f"- Scripted suite: {len(clean['scripted']['failed'])} failures of {clean['scripted']['tests']} tests.")
    for chooser in ("random", "llm"):
        for r in clean.get(chooser, []):
            label = f"seed {5 if r['run'] == 1 else r['run']}" if chooser == "llm" else f"run {r['run']}"
            lines.append(f"- {chooser} {label}: {len(r['findings'])} findings"
                         + (f" ({'; '.join(f['detail'] for f in r['findings'])})" if r["findings"] else ""))
    lines += ["", "## Details", ""]
    for name, description in CATALOGUE.items():
        row = by_fault.get(name, {})
        lines += [f"### `{name}`", "", description, ""]
        s = row.get("scripted")
        if s:
            lines.append("Scripted suite: " + (", ".join(f"`{t}`" for t in s["failed"][:8])
                                               + (f" and {len(s['failed']) - 8} more" if len(s["failed"]) > 8 else "")
                                               if s["failed"] else "no test failed."))
        for chooser in ("random", "llm"):
            for r in row.get(chooser, []):
                found = "; ".join(f"step {f['step']} {f['rule']}: {f['detail']}" for f in r["findings"]) or "nothing"
                label = f"seed {5 if r['run'] == 1 else r['run']}" if chooser == "llm" else f"run {r['run']}"
                lines.append(f"- {chooser} {label}: {found}")
        lines.append("")
    if explorers:
        lines += ["## Cost", "",
                  f"Model explorer: {explorers['model_calls']} model calls, {explorers['model_seconds']} s of model time "
                  "on the laptop CPU, no paid service.", ""]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:22]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
