# Verification and release assessment

What was actually run, what it showed, and what it does not show. Every figure here comes from a saved file under `evidence/` or from a command that can be re-run. The plan these checks follow is [TEST_PLAN.md](TEST_PLAN.md).

## 1. Environment actually exercised

| Item | Value |
|---|---|
| Machine | The development laptop: Windows 11 Enterprise, 16 logical processors |
| Python | 3.12.10, packages pinned in `requirements-lock.txt` |
| Browser | Installed Google Chrome, driven headless by Playwright 1.64.1 |
| Server | One uvicorn process on 127.0.0.1, one SQLite file in WAL mode |
| Language model (AI tools only) | Ollama with `llama3.2` (3B), local CPU |
| Not exercised | Other browsers, other operating systems, any deployment. Hosted CI results are not recorded here |

## 2. Automated tests

Final full run on the final code, in a fresh virtual environment built in `%TEMP%` from `requirements.txt` alone, which is what `requirements-lock.txt` was frozen from (Python 3.12.10, Playwright 1.64.1): `python -m pytest`: **197 passed in 185 s**. After the last checker fixes (a stronger focus-ring comparison and recaptured screenshots), the suite was run again in the project environment: **197 passed in 155 s**.

**Fresh clone, following the README.** The repository was cloned into a new folder and the README's commands were run as written, in Windows PowerShell 5.1 on Windows 11 (build 26100) with Python 3.12.10: the virtual environment and `pip install -r requirements-lock.txt` installed cleanly (`pip check`: no broken requirements); `serve.py --sample-sales 0.55` answered, signed in as Le Jie, with 510 seats of which 275 were sold to sample accounts; `pytest` passed 197 of 197 in 157 s; the load test passed every integrity check (run 4 below); and the security scan passed.

| Suite | Tests | What it checks |
|---|---|---|
| `tests/api` | 155 | Rules, boundaries, payment recovery, every account route without a valid token, error shapes, 52 generated inputs |
| `tests/security` | 22 | Cross-account access, abuse limits, headers (also on a 500), hardening of the real server with test hooks off |
| `tests/concurrency` | 5 | Parallel requests against a live server, checked in the database |
| `tests/e2e` | 15 | Browser journeys in headless Chrome |
| **Total** | **197** | |

Every new regression test was also run against the code before its fix, to confirm it can fail: the settle-recovery test failed on the old checkout (first a plain-text 500, then a 409 where 200 was expected), and the double-submit browser test counted 2 payment requests on the old page and 1 on the fixed one. See [DEFECTS.md](DEFECTS.md) DEF-007 and DEF-008. The same was done for the fixes from the multi-agent review (DEF-012, DEF-013, and the server changes for headers on a 500, the `/api` error shape, foreign host names, the rate-limit clock, late decline messages, a reused payment key and the limit message); each commit body records its before and after result.

## 3. Load

Four runs of `tools/run_load_test.py`: 200 simulated fans started within one second, 60 seconds, sale opening five seconds after start, one server process sharing the laptop with the load generator.

| Run | Code | Requests | Server errors | Median ms | p95 ms | Avg req/s | Integrity checks | Tickets |
|---|---|---|---|---|---|---|---|---|
| 1 | before the read-path change | 1245 | 0 | 970 | 3000 | 20.8 | all passed | 92 |
| 2 | after the read-path change | 1557 | 0 | 2100 | 5100 | 25.9 | all passed | 123 |
| 3 | after the checkout recovery change | 1160 | 0 | 2900 | 5400 | 19.3 | all passed | 60 |
| 4 | final code, from a fresh clone | 1066 | 0 | 2900 | 4700 | 17.8 | all passed | 59 |

Runs 1 and 4 are saved under [evidence/load/before-read-path-fix](../evidence/load/before-read-path-fix/SUMMARY.md) and [evidence/load](../evidence/load/SUMMARY.md). The figures for runs 2 and 3 are transcribed from their saved output before later runs replaced the files.

**What it shows.** In every run: zero server errors, no seat sold twice, no sold seat without a ticket, no ticket on an unsold seat, no account over four seats, no payment left pending, and money charged exactly equal to the value of the tickets issued.

**What it does not show.** A capacity or latency figure for production. Latency varied by a factor of three between runs on the same laptop, which also ran the load generator and, at times, other work. The throughput ceiling is CPU in one Python process (DEF-002).

## 4. Static security scans

From `tools/security_scan.py`, saved in [evidence/security/SUMMARY.md](../evidence/security/SUMMARY.md). Last run with a fresh virtual environment built from `requirements-lock.txt`; the script exits non-zero if a scan does not run, a dependency is vulnerable, or bandit reports anything beyond the two triaged findings.

| Scan | Result | Triage |
|---|---|---|
| bandit on `app/` | 2 findings, both low severity | B105 `demo-pass`: the documented demo password, accepted for demo accounts only. B311 `random`: used only to choose sample sales, not for anything secret. Tokens and salts use `secrets` and `os.urandom` |
| pip-audit on `requirements-lock.txt` | 84 packages, 0 known vulnerabilities | Result is for the day of the run; the database of known vulnerabilities changes |

## 5. Generated test data

From `ai/datagen.py`, saved in [evidence/ai/datagen_report.md](../evidence/ai/datagen_report.md). 52 unique inputs proposed by the local model across four fields, all new compared with the hand-written cases. The model's own valid or invalid label was right for 44 of 52; it is never used as the expected result. The application agreed with the written input rules on all 52, and the inputs are replayed by `tests/api/test_generated_inputs.py`.

## 6. Seeded faults

Full method and per-fault details: [FAULT_INJECTION.md](FAULT_INJECTION.md) and [evidence/faults/REPORT.md](../evidence/faults/REPORT.md).

- Ten faults, planted by a separate agent that never read the tests.
- Scripted suite on the final code: caught **8 of 10**, with 0 failures on the clean application (158 tests at the time).
- The two escaped faults were then closed with one new test (a fan signed in twice is still rate limited) and one tightened assertion (the page re-reads the map within 1.5 s of a refusal); a follow-up run shows both caught and the clean suite at 159 passing ([scripted-after-gap-tests.json](../evidence/faults/scripted-after-gap-tests.json)).
- Exploratory testing, 30 actions per run, the same rule checks for both explorers, 0 false alarms on the clean application: the random explorer caught 2 of 10 and the local model explorer 1 of 10, each with three seeds per fault. The model's transcript shows why: it repeated actions on a seat it had already bought and did not use the refusals it received. See [FAULT_INJECTION.md](FAULT_INJECTION.md).

## 7. Defects

Real defects and investigations are in [DEFECTS.md](DEFECTS.md): thirteen entries. Eleven are fixed or worked around, one (throughput, DEF-002) is partly improved with its limit recorded, and one (DEF-010) records four minor review observations that were accepted. The two high-severity defects are fixed: DEF-007 was found by a separate review agent, and DEF-012, which made DEF-007's recovery unreachable from the page, by a later multi-agent review. None remains open against R2 or R5 to R9.

## 8. Status of each kind of claim

| Behaviour | Status |
|---|---|
| Booking rules R1 to R13 | Implemented and tested automatically |
| Behaviour under a 200-fan burst on one laptop (R14) | Tested; latency is an observation |
| Browser journeys in Chrome on Windows | Tested |
| Keyboard operation of the seat map | Tested for one path; no screen-reader testing |
| Payment | Simulated by a mock gateway; no real provider was integrated |
| AI-generated data and exploration | Measured on one small local model: one seed for data generation, three seeds per fault for exploration; not a general claim about language models |
| Hosted CI (`.github/workflows/ci.yml`) | Runs on GitHub for pull requests and pushes to main; its results are not recorded in this document |
| Showcase page on GitHub Pages | Prepared; whether it has been published is not recorded here |
| Production readiness, capacity, accessibility compliance | Not claimed |

## 9. Release assessment

**Recommendation: ready for review. Published as a private repository; making it public is the owner's decision. Not production software.**

Basis:

- All 197 automated tests pass on the final code (run recorded in section 2).
- Every requirement R1 to R14 has automated checks; the riskiest ones (R2, R5 to R9, R14) have several kinds.
- The load runs show no server errors and no data damage under a 200-fan burst.
- Both high-severity defects found (DEF-007, DEF-012) are fixed, each with a regression test proven to fail on the old code.
- Static scans are triaged; no known vulnerable dependency on the day of the scan.

Open items, none blocking a private release:

- Throughput is limited to roughly 20 to 26 requests per second on the laptop (DEF-002).
- No reconciliation for a process crash, or a database locked for about 30 s, between the gateway charge and recording its outcome (DEF-007, remaining limit).
- Hosted CI results and the showcase page's publication are not recorded here; the owner confirms them.
- Only Chrome on Windows was exercised.
