"""Run the static security scans and save their reports under evidence/security.

    .venv\\Scripts\\python.exe tools\\security_scan.py            # bandit and pip-audit
    .venv\\Scripts\\python.exe tools\\security_scan.py --offline  # bandit only, no network

bandit reads the application source for risky patterns. pip-audit checks the
locked dependency versions against the public PyPI vulnerability database,
so it needs an internet connection.

The evidence files are always written first. The exit code is then non-zero
if bandit did not run, if pip-audit produced no report (unless --offline),
if any dependency has a known vulnerability, or if bandit reports anything
outside the triaged allowlist below. That makes the CI step able to fail.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "security"
# Triaged in docs/VERIFICATION.md section 4: the documented demo password, and
# random.Random used only to pick sample sales. Anything else fails the scan.
BANDIT_ALLOWED = {"B105", "B311"}


def run(args):
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run bandit and pip-audit and save the evidence.")
    parser.add_argument("--offline", action="store_true", help="Skip pip-audit, which needs the network.")
    args = parser.parse_args(argv)
    problems = []

    OUT.mkdir(parents=True, exist_ok=True)
    bandit = run(["bandit", "-r", "app", "-f", "json", "-q"])
    (OUT / "bandit.json").write_text(bandit.stdout, encoding="utf-8")
    try:
        # bandit exits 0 with no findings and 1 with findings; anything else means it did not run.
        if bandit.returncode not in (0, 1):
            raise ValueError(f"exit code {bandit.returncode}")
        bandit_issues = json.loads(bandit.stdout)["results"]
    except (ValueError, KeyError) as exc:  # json.JSONDecodeError is a ValueError.
        bandit_issues = []
        problems.append(f"bandit did not run ({exc}): {bandit.stderr.strip()[:300]}")
    unexpected = [i for i in bandit_issues if i["test_id"] not in BANDIT_ALLOWED]
    if unexpected:
        problems.append(f"bandit: {len(unexpected)} finding(s) outside the allowlist {sorted(BANDIT_ALLOWED)}")

    vulnerable = []
    if args.offline:
        audit_summary = "skipped (--offline)"
    else:
        audit = run(["pip_audit", "-r", "requirements-lock.txt", "--format", "json", "--progress-spinner", "off"])
        (OUT / "pip-audit.json").write_text(audit.stdout or audit.stderr, encoding="utf-8")
        try:
            deps = json.loads(audit.stdout)["dependencies"]
            vulnerable = [d for d in deps if d.get("vulns")]
            audit_summary = f"{len(deps)} packages checked, {len(vulnerable)} with known vulnerabilities"
            if vulnerable:
                problems.append(f"pip-audit: {len(vulnerable)} package(s) with known vulnerabilities")
        except (json.JSONDecodeError, KeyError):
            audit_summary = "pip-audit did not produce a report (no network?): see pip-audit.json"
            problems.append("pip-audit produced no report")

    lines = [
        "# Static security scan",
        "",
        f"Run at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        f"- bandit on `app/`: {len(bandit_issues)} findings",
    ]
    for issue in bandit_issues:
        lines.append(f"  - {issue['test_id']} {issue['issue_severity']}/{issue['issue_confidence']}"
                     f" {issue['filename']}:{issue['line_number']} {issue['issue_text']}")
    lines.append(f"- pip-audit on `requirements-lock.txt`: {audit_summary}")
    for dep in vulnerable:
        for v in dep["vulns"]:
            lines.append(f"  - {dep['name']} {dep['version']}: {v['id']} (fixed in {', '.join(v.get('fix_versions', [])) or 'no fix yet'})")
    lines.append("")
    lines.append("Result: " + ("FAIL: " + "; ".join(problems) if problems else "PASS"))
    if not args.offline:  # An offline run leaves the saved pip-audit evidence as it was.
        (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
