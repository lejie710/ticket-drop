# Defect log

Real defects and investigations found while building and testing Ticket Drop. Seeded faults, which were planted on purpose to measure the tests, are a separate thing and live in [FAULT_INJECTION.md](FAULT_INJECTION.md).

Each entry records what was observed, the hypothesis, the evidence, and the outcome, including hypotheses that turned out wrong.

| ID | Area | Summary | Status |
|---|---|---|---|
| DEF-001 | Test harness | Race tests took 113 s; cause was the test client, not the server | Fixed |
| DEF-002 | Performance | Spike throughput about 21 requests per second; read path took the write lock | Partly improved, limit recorded |
| DEF-003 | Security | Responses advertised the server software (`server: uvicorn`) | Fixed |
| DEF-004 | Test environment | pytest could not clean its temporary folder on this laptop | Worked around |
| DEF-005 | UI | Clicking a seat drew a square focus outline around the round seat | Fixed |
| DEF-006 | Tooling | The test-data generator crashed when printing a generated Unicode character | Fixed |
| DEF-007 | Checkout | A failure while settling left the fan charged, without tickets, and locked out | Fixed, regression test |
| DEF-008 | UI | Enter in the card field sent a second payment request while one was in flight | Fixed, regression test |
| DEF-009 | UI, checkout | A kept payment key could be reused for a different set of seats | Fixed in the page and on the server, regression tests |
| DEF-010 | Review notes | Four minor observations | Recorded, not fixed |
| DEF-011 | UI | On a phone the header wrapped and the payment strip covered almost half the screen | Fixed |
| DEF-012 | UI, checkout | After a 500 the page dropped its payment key, so DEF-007's recovery could not be reached from the browser | Fixed, regression test |
| DEF-013 | UI | Six smaller front-end faults: keyboard, focus, stale notice, Release while paying, phone summary, contrast | Fixed, regression tests for four |

DEF-007 to DEF-010 were found by a separate review agent that read the requirements, design, code and tests without seeing the author's reasoning, and reported findings without editing anything. DEF-012 and DEF-013 were found later by a multi-agent review (separate agents per area, each finding then checked by another agent trying to disprove it) and reproduced before fixing.

## DEF-001: race tests were slow, and the first explanation was wrong

**Observed.** The five concurrency tests took 113 seconds. Fifty parallel requests for one seat took 34 seconds by themselves.

**First hypothesis, rejected.** SQLite's busy handler waits in growing sleeps of up to 100 ms when a writer finds the database locked, so fifty writers queueing could add up. I added an in-process write lock to stop the polling and moved the WAL pragma out of the per-connection setup. The test still took 29 seconds, so this was not the cause. The write lock was removed again rather than kept as an unproven fix. Setting WAL once at start-up was kept because it is correct regardless.

**Measured.** A small script timed each part separately against a live server:

| Operation | Time |
|---|---|
| 50 sign-ins, one after another, each with `httpx.post()` | 24.35 s |
| 20 reads with `httpx.post()`-style one-off clients | 7.38 s |
| The same 20 reads through one shared `httpx.Client` | 0.19 s |
| 50 parallel seat claims, server side | about 4.4 s, mostly client start-up |

**Cause.** A bare `httpx.post()` builds and tears down a client for every call, which cost about 0.37 s each on this machine. The server was not the bottleneck.

**Fix.** `tests/support/live_server.py` keeps one thread-safe `httpx.Client` per server. The concurrency suite went from 113 s to 26 s with no change to application code.

**Lesson.** Measure each layer before changing the system under test. The first fix was plausible, cheap and wrong.

## DEF-002: throughput under the sale-opening spike

**Observed.** The first Locust spike (200 fans for 60 seconds) completed with no server errors and no double sales, but averaged only about 21 requests per second, with median latency near 1 s. Evidence: [evidence/load/before-read-path-fix/SUMMARY.md](../evidence/load/before-read-path-fix/SUMMARY.md).

A reporting bug was found at the same time: the summary copied Locust's `Requests/s` column, which is the rate near the end of the run, and showed 93 requests per second. The summary now divides the request count by the duration.

**Hypothesis.** `GET /api/seats` and `GET /api/hold` opened a write transaction on every call to expire overdue holds first, so every read waited behind every seat claim.

**Change.** Read endpoints now check for an overdue hold with a plain read and take the write lock only when something actually needs expiring (`expire_if_due` in `app/service.py`), then read inside a snapshot transaction. Indexes were added for the overdue-hold check.

**Result.** Throughput rose only from about 21 to 26 requests per second, and median latency did not improve. The 26 requests per second (25.9) is from the run straight after the change; its figures are transcribed from console output in [VERIFICATION.md](VERIFICATION.md) section 3, because its files were overwritten by a later run. The saved run, [evidence/load/SUMMARY.md](../evidence/load/SUMMARY.md), is the final code run from a fresh clone: 17.8 requests per second, median 2.9 s, p95 4.7 s, on the same laptop. The change is kept because reads no longer queue behind writes, but it was not the main limit.

**Where the time actually goes.** Unloaded, one seat-map request costs about 16 ms of server time, a hold read about 7 ms, and a sign-in about 74 ms (deliberately slow password hashing). All of it runs in one Python process that shares this laptop's CPU with Locust itself. The ceiling is CPU in a single process, not lock contention.

**Status.** Recorded as a known limit, not fixed. Options for a later version: cache the seat map for a short time, return only changed seats, move password hashing cost off the spike by signing in before the sale, or run several processes with a shared rate limiter. None is needed for the correctness goals of version 1.

## DEF-003: server software advertised in responses

**Found by** a security review of response headers. uvicorn adds `server: uvicorn` to every response, which tells an attacker what to look up.

**Fix.** `serve.py` starts uvicorn with `server_header=False`. `tests/security/test_live_server_hardening.py` checks the header is absent on the real server process.

## DEF-004: pytest temporary folder blocked on this laptop

**Observed.** The first test run passed every test, then crashed while cleaning up with `PermissionError: [WinError 5] Access is denied` on `AppData\Local\Temp\pytest-of-<username>\pytest-current`, a symbolic link pytest creates. On this managed laptop that location cannot be read back.

**Workaround.** `pyproject.toml` sets `--basetemp=.local/pytest`, a folder inside the project that `.gitignore` excludes, and `tests/conftest.py` creates `.local` if a fresh clone lacks it. This is an environment issue, not an application defect.

## DEF-005: square focus outline on round seats

**Observed** in the rendered UI: after a click, Chrome drew its rectangular focus outline around the circular seat, overlapping its neighbours.

**Fix.** Seats hide the default outline and show keyboard focus with a ring that follows the circle (`.seat.focused`).

**Correction.** This entry used to say `test_seats_can_be_chosen_with_the_keyboard_only` showed that focus stays visible. It did not: it checks which seat has focus, not what is drawn. A later review found that tabbing into the map drew no ring at all, because the ring was added only on arrow keys (DEF-013). `test_tabbing_into_the_map_shows_a_focus_ring` now checks the class within one second and that the focused seat's computed stroke differs from an unfocused seat of the same category (A-02), which has no stroke of its own.

## DEF-006: generator crashed printing its own report

**Observed.** `ai/datagen.py` finished its work and saved its files, then crashed printing the report: the model had produced `U+FFFC`, which the Windows console code page cannot encode.

**Fix.** The script reconfigures standard output to UTF-8 with replacement. The saved report was never affected.

## DEF-007: charged, no tickets, and locked out

**Severity.** High. This is the project's central failure: paying without getting tickets.

**Scenario.** Checkout reserves (transaction 1), charges through the gateway, then settles (transaction 2). If transaction 2 failed after the gateway had charged, for example because the database stayed locked past the ten-second busy timeout during a burst:

- the ledger held one charge and the fan had no tickets;
- the payment stayed `pending` and the hold stayed `paying`, so expiry never released the seats;
- every retry with the same key answered 409 `checkout_in_progress`, and so did releasing seats or adding new ones;
- the server answered with a plain-text "Internal Server Error" instead of the JSON error shape.

**Reproduced** by the reviewer by making the second transaction raise, and again here by `test_settle_failure_is_finished_by_a_retry_without_charging_again`, which fails on the old code twice over. First, the 500 was not JSON. Then, with only the error handler fixed, the retry answered `409` instead of `200`.

**Fix** (`app/service.py`):

- The gateway's outcome is written to the payment row immediately after the call, in its own statement, retried briefly if the database is busy.
- Settling became `settle_payment`, which reads the recorded outcome and is safe to run more than once: it returns the stored response if another request already settled.
- Settling retries up to three times when the database is busy.
- If settling still fails, a retry with the same idempotency key finishes the settle and issues the tickets without charging again. This recovery needs the client to resend the same key after a 500. The page did not do that until DEF-012 was fixed; it now does.
- `app/main.py` gained a catch-all handler that returns the normal JSON error shape for unexpected errors, with no internal detail.

**Remaining limit.** If the process dies, or the database stays locked for about 30 seconds, between the gateway charge and recording its outcome, the payment stays `pending` and every retry with that key answers 409 `checkout_in_progress`, although the 500 told the fan to try again. That needs a reconciliation job against the gateway, which version 1 does not have.

**Related decisions made while fixing.**

- A payment that started before the hold expired is honoured even if the gateway answers after the expiry instant. The seats were protected as `paying` the whole time. `test_a_payment_started_in_time_is_honoured_after_the_expiry` records the rule.
- A decline that arrives after the expiry instant frees the seats at once (`test_hold_expiring_during_a_declined_payment_frees_the_seats_at_once`).
- Releasing one seat while a payment is in flight now answers 409 `checkout_in_progress`, consistent with the other seat changes, instead of 404.

## DEF-008: Enter sent a second payment

**Scenario.** The card field sits in a form with no submit button, so pressing Enter submits the form, and that called `pay()` even while the Pay button was disabled. A second request with the same key reached the server, which correctly refused it with 409. The page then treated that refusal as the end of the payment, unlocked the seat controls and cleared the key while the first payment was still in flight.

**Fix.** `pay()` returns immediately while a payment is in progress.

**Test.** `test_pressing_enter_twice_sends_one_payment` counts the checkout requests the browser actually sends. The old page sent 2 and the fixed page sends 1. A check of the database alone could not show this bug, because the server's own protection hid it.

## DEF-009: a kept payment key reused for different seats

**Scenario.** After a request that got no answer, the page keeps its idempotency key so a retry cannot charge twice. Nothing cleared that key if the fan then changed seats, so a later payment for a different basket could replay the old result: either "Payment complete" while the new seats stayed unpaid, or an old decline.

**Fix.** The key is remembered together with the hold and the exact seats, reused only when both are unchanged, and cleared on sign-out.

**Enforced on the server too** (after a later multi-agent review). The page fix relied on every client behaving. The server now refuses a stored key when the account's current open hold is a different hold from the one that key paid for: 409 `idempotency_key_reused`, no charge, the new hold untouched. Replaying the same hold, or a completed payment when no new hold is open, still returns the stored result exactly. Tests: `test_a_paid_key_cannot_be_reused_for_new_seats` and `test_a_declined_key_cannot_be_reused_after_choosing_seats_again` (both fail on the previous server, which replayed the old 200 or 402), and in the browser `test_a_kept_payment_key_is_not_reused_for_different_seats`, which fails when the page's basket check is removed.

## DEF-010: minor review observations, recorded

| Observation | Assessment |
|---|---|
| A malformed seat ID in the URL still spends a rate-limit token, because the limit is checked before validation | Harmless: it only makes an abusive client slower |
| Several wrong passwords sent at exactly the same moment can exceed ten per minute, because the window is checked before it is recorded | Small overshoot under deliberate concurrency; acceptable for version 1 |
| Session tokens never expire | Acceptable for demo accounts; a real service would expire them |
| The API tests use a zero-second gateway timeout, so the real `paying` window was not exercised | Addressed by the new tests that slow the gateway down artificially |

## DEF-011: phone layout too crowded

**Found by** looking at the real screenshots taken for the documentation, not by a test: at 390 px wide the wordmark broke onto two lines, and the docked payment strip covered about 45 percent of the screen, hiding most of the seat map.

**Fix.** On phones the "Signed in as" text and the timer note are hidden, the test-card help is smaller, and the timer sits beside the card field. The strip covered about 29 percent of the screen after this fix; the held-seat summary added later (DEF-013) makes it about 34 percent. `test_phone_layout_docks_the_payment_strip` still checks that the strip is docked to the bottom edge and the Pay button is visible; a test cannot judge "crowded", which is why screenshots are reviewed by eye.

## DEF-012: the page dropped its payment key after a server error

**Severity.** High, because it made DEF-007's fix unreachable for a real fan.

**Scenario.** DEF-007's recovery works only if the client repeats the same idempotency key. After a 500 the page treated the answer as final and threw its key away, so the next click on Pay sent a new key. The first attempt had already been charged and its hold stayed `paying`, so the fan was charged, got no tickets, and every new attempt was refused with 409 `checkout_in_progress`.

**Found by** the multi-agent review and reproduced by forcing a 500 on the first checkout in the browser.

**Fix** (`app/static/app.js`, commit 6eb5db0). The page keeps its key after any 5xx other than the gateway's 504, as it already did when there was no answer at all. The kept key is still tied to the same hold and seats (DEF-009).

**Test.** `test_retry_after_a_server_error_reuses_the_payment_key` answers the first checkout with a 500, clicks Pay again and expects the same `Idempotency-Key` and one ticket. It fails on the old page, which sent a different key.

## DEF-013: smaller front-end faults from the same review

All fixed in commit 6eb5db0. Each new browser test fails on the previous page.

| Fault | Fix | Test |
|---|---|---|
| Enter after clicking a seat acted on the old tab stop, a different seat | The key handler uses the seat that has focus, and the tab stop follows clicks | `test_enter_after_a_click_acts_on_the_clicked_seat` |
| Tabbing into the map showed no focus ring (see the DEF-005 correction) | The focus listener adds the ring; the ring is blue, so it differs from a held seat even with reduced motion | `test_tabbing_into_the_map_shows_a_focus_ring` |
| A decline or expiry notice stayed on screen after the fan picked new seats | A successful seat change clears the notice | `test_a_new_seat_clears_an_old_payment_message` |
| On a phone the held seats and total were hidden | The docked strip names the held seats and the total | `test_phone_layout_docks_the_payment_strip` (now asserts the text) |
| Release seats stayed clickable while a payment was in flight | Hidden while paying, and ignored if clicked | None; checked by reading the code |
| Some text, the tier-3 seats and the input border were below WCAG contrast | Darker text teal (#146B68, about 5.6:1), a darker tier-3 stroke, a darker input border | None; ratios computed by hand. Accessibility compliance is still not claimed |
