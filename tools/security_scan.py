"""Run the static security scans and save their reports under evidence/security.

    .venv\\Scripts\\python.exe tools\\security_scan.py

bandit reads the application source for risky patterns. pip-audit checks the
locked dependency versions against the public PyPI vulnerability database,
so it needs an internet connection.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "security"


def run(args):
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bandit = run(["bandit", "-r", "app", "-f", "json", "-q"])
    (OUT / "bandit.json").write_text(bandit.stdout, encoding="utf-8")
    bandit_issues = json.loads(bandit.stdout)["results"] if bandit.stdout.strip() else []

    audit = run(["pip_audit", "-r", "requirements-lock.txt", "--format", "json", "--progress-spinner", "off"])
    (OUT / "pip-audit.json").write_text(audit.stdout or audit.stderr, encoding="utf-8")
    try:
        deps = json.loads(audit.stdout)["dependencies"]
        vulnerable = [d for d in deps if d.get("vulns")]
        audit_summary = f"{len(deps)} packages checked, {len(vulnerable)} with known vulnerabilities"
    except (json.JSONDecodeError, KeyError):
        vulnerable = None
        audit_summary = "pip-audit did not produce a report (no network?): see pip-audit.json"

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
    for dep in vulnerable or []:
        for v in dep["vulns"]:
            lines.append(f"  - {dep['name']} {dep['version']}: {v['id']} (fixed in {', '.join(v.get('fix_versions', [])) or 'no fix yet'})")
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
