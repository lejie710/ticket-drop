# Test plan

Risk-based: the requirements whose failure would hurt fans or money most get the most varied and the deepest checks. Requirements are in [BRIEF.md](BRIEF.md); results are in [VERIFICATION.md](VERIFICATION.md).

## 1. Scope

In scope: the HTTP API, booking rules, payment handling with the mock gateway, the browser interface in Chrome, behaviour under concurrent and burst load on one local server, and the security of one account against another.

Out of scope for version 1: real payment providers, browsers other than Chrome, accessibility beyond keyboard operation and visible focus, multi-process or multi-machine deployment, and production-scale capacity.

## 2. Risk assessment

Impact: what happens to a fan or to money if the requirement fails. Likelihood: how easy it is for a reasonable implementation to get wrong.

| Req | Risk if it fails | Impact | Likelihood | Priority |
|---|---|---|---|---|
| R2 | Two fans sold the same seat | High | High under concurrency | 1 |
| R6 | Fan charged without tickets, or loses seats after a decline | High | Medium (error paths) | 1 |
| R7 | Fan charged twice for one order | High | Medium | 1 |
| R9 | One fan reads or releases another fan's seats or tickets | High | Medium | 1 |
| R14 | Errors or data damage at the sale opening | High | Medium | 1 |
| R5 | Payment succeeds but tickets are wrong or missing | High | Low | 2 |
| R8 | Client sets its own price | High | Low | 2 |
| R4 | Seats released early or late | Medium | High (time boundary) | 2 |
| R3 | One account takes more than its share | Medium | Medium | 2 |
| R1 | Seats taken before the official opening | Medium | Medium | 2 |
| R13 | Released seats never return to sale | Medium | Medium | 2 |
| R10 | Bots or scripts flood seat changes or guess passwords | Medium | Medium | 3 |
| R11 | Map shows a seat wrongly, fan confused | Medium | Medium | 3 |
| R12 | Malformed input changes state or leaks internals | Medium | Low | 3 |

## 3. Test levels and what each one is for

| Level | Where | Tool | What it can prove | What it cannot |
|---|---|---|---|---|
| API | `tests/api` | pytest, Starlette TestClient, frozen clock | Every rule on exact boundaries, fast and deterministic | Real parallelism, the browser |
| Security | `tests/security` | pytest | Cross-account access, abuse limits, headers, hardening of the real server | Unknown attack classes |
| Concurrency | `tests/concurrency` | pytest, threads behind a barrier, live server | Rules hold when requests truly overlap | Timing on other hardware |
| Browser | `tests/e2e` | Playwright on installed Chrome | What a fan sees and does, including keyboard use and the phone layout | Other browsers, screen readers |
| Load | `load/`, `tools/run_load_test.py` | Locust plus a database integrity check | No errors or damage under a 200-fan burst; latency as an observation | A service level for production |
| Static security | `tools/security_scan.py` | bandit, pip-audit | Known risky code patterns and vulnerable dependency versions | Logic flaws |
| Generated data | `ai/datagen.py`, `tests/api/test_generated_inputs.py` | local model plus a rule oracle | Validation against inputs nobody wrote by hand | Anything beyond input validation |
| Exploratory | `ai/explorer.py`, `tools/run_explorers.py` | local model or random choice, shared rule checks | Whether an automated explorer finds planted faults | Completeness: it samples behaviour |
| Test effectiveness | `tools/fault_matrix.py` | the whole suite against each seeded fault | Which approach catches which kind of bug | Bugs unlike the planted ones |

## 4. Test design techniques used

| Technique | Applied to | Example |
|---|---|---|
| Boundary value analysis | R1, R3, R4 | Hold valid at 299 999 ms, ended at exactly 300 000 ms; sale closed at opening minus 1 ms, open at the opening instant; 4 seats allowed, the fifth refused |
| Equivalence partitioning | R12 | Seat IDs: valid, wrong row letter, lower case, wrong digit count, injection-shaped text, wrong JSON type |
| Decision table | R6, R7 | Card outcome (pay, decline, timeout) by key (new, repeated) by hold (open, expired, none). Covered: every outcome with a new key on an open hold; repeated keys for all three outcomes on an open hold; a repeated paid key after expiry. Not covered: a repeated declined or timed-out key after the hold has expired |
| State transition | R4 to R7, R13 | Hold states below |
| Error guessing and negative testing | R8, R9, R12 | A client-sent price, another account's ticket ID, a key reused across accounts |
| Concurrency testing | R2, R3, R7 | 50 fans on one seat; 10 parallel claims by one fan; 5 parallel Pay clicks |
| Exploratory testing | All | An agent choosing actions from the rules, compared with random choice |
| Fault injection | All | Ten seeded faults, planted blind, to measure detection |

### Hold state transitions

| From | Event | To | Seats |
|---|---|---|---|
| (none) | first seat held | active | held |
| active | seat released, others remain | active | that seat available |
| active | last seat released, or release all | released | available |
| active | expiry instant reached | expired | available |
| active | checkout starts | paying | still held, protected from expiry |
| paying | gateway succeeds | paid | sold, tickets issued |
| paying | gateway declines or times out | active | still held until the original expiry |
| paying | gateway declines or times out after the expiry instant | expired | available; the answer says the hold has expired |

Each row has at least one API test. The rows on error paths also have browser tests.

## 5. Requirement coverage

| Req | API | Security | Concurrency | Browser | Load | Explorer check |
|---|---|---|---|---|---|---|
| R1 | `test_time_rules` (3) | | | `test_before_the_sale_opens` | sale opens during the spike | hold before opening |
| R2 | `test_holds` | | 50 fans, crowd | `test_seat_taken_while_the_map_was_open` | integrity check | crowd hold |
| R3 | `test_limits` (7) | | parallel claims | `test_fifth_seat_shows_the_limit` | integrity check | over-limit |
| R4 | `test_time_rules` (5), a `paying` hold survives another fan's expiry sweep (`test_checkout_recovery`) | | | `test_expired_hold_is_explained_and_seats_return` | | overdue hold |
| R5 | `test_checkout`, `test_tickets`, `test_checkout_recovery` | | crowd | `test_fan_holds_two_seats_and_pays` | money matches tickets | money matches tickets |
| R6 | `test_checkout` (4), `test_checkout_recovery` (2) | | | `test_declined_card_keeps_the_seats`, `test_pressing_enter_twice_sends_one_payment` | | seats kept after failure |
| R7 | `test_checkout` (6: success, decline and timeout replays, replay after the expiry, a key refused for a different hold twice), settle recovery | key scoped to account | double click, parallel retries | `test_retry_after_a_server_error_reuses_the_payment_key`, `test_a_kept_payment_key_is_not_reused_for_different_seats` | | repeated key |
| R8 | `test_the_client_cannot_set_the_price` | | | | money matches tickets | money matches tickets |
| R9 | `test_auth` (every account route, missing and made-up token), `test_tickets` | `test_access_control` (5 cross-account tests), foreign `Host` refused on the real server | | | | cross-account access |
| R10 | | `test_abuse_and_headers` (5) | | | 429 counted as correct | rapid changes |
| R11 | `test_holds` | | | map states in every journey | | map versus database |
| R12 | `test_validation` (bodies, address IDs, cards, keys, error shape for unknown addresses), generated inputs | | | | no 5xx | no 5xx |
| R13 | `test_holds` (3) | release only own hold | | | | seats stuck under closed hold |
| R14 | | | | | `tools/run_load_test.py` | |

## 6. Entry and exit criteria

Entry: the requirement has an ID in the brief, and a test names it before the feature is called done.

Exit for a release:

- Every automated test passes on the clean application, run from a fresh clone.
- The load run reports zero server errors and passes every integrity check.
- No open defect affects R2, R5 to R9.
- bandit findings are triaged, and pip-audit reports no known vulnerability.
- Every seeded fault that escapes the scripted suite is explained in [FAULT_INJECTION.md](FAULT_INJECTION.md).

## 7. Environment

Windows 11, Python 3.12, Google Chrome (driven headless), local Ollama with `llama3.2` for the AI tools only. One server process with one SQLite file. The tests start and stop their own servers on free ports and never touch the demo database.
