# Static security scan

Run at 2026-11-03 18:41 UTC.

- bandit on `app/`: 2 findings
  - B105 LOW/MEDIUM app\db.py:84 Possible hardcoded password: 'demo-pass'
  - B311 LOW/HIGH app\db.py:154 Standard pseudo-random generators are not suitable for security/cryptographic purposes.
- pip-audit on `requirements-lock.txt`: 95 packages checked, 0 with known vulnerabilities
