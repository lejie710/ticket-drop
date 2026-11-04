# Seeded faults: which approach caught what

Caught means: the scripted suite had at least one failing test, or an explorer run raised at least one finding.
Random baseline: 3 runs per fault with different seeds; shown as runs that found it.
Model explorer: ollama:llama3.2, seeds 5, 6, 7, one run per seed per fault; shown as runs that found it. 30 actions per run.

| Fault | Req | Scripted suite | Random explorer | Model explorer |
|---|---|---|---|---|
| `seat_checked_before_lock` | R2 | caught, 3 test(s) | 1/3 runs | 1/3 runs |
| `limit_ignores_owned_tickets` | R3 | caught, 1 test(s) | 0/3 runs | 0/3 runs |
| `hold_expiry_boundary_exclusive` | R4 | caught, 4 test(s) | 0/3 runs | 0/3 runs |
| `timeout_leaves_hold_paying` | R6 | caught, 1 test(s) | 0/3 runs | 0/3 runs |
| `idempotency_reruns_failed_payment` | R7 | caught, 1 test(s) | 0/3 runs | 0/3 runs |
| `client_sets_amount` | R8 | caught, 1 test(s) | 0/3 runs | 0/3 runs |
| `remove_seat_from_any_hold` | R9, R13 | caught, 2 test(s) | 0/3 runs | 0/3 runs |
| `seat_rate_limit_per_session` | R10 | missed | 0/3 runs | 0/3 runs |
| `map_stale_after_failed_seat_change` | R11 | missed | 0/3 runs | 0/3 runs |
| `release_hold_leaves_seats_held` | R13 | caught, 2 test(s) | 1/3 runs | 0/3 runs |

Totals: scripted 8/10, random explorer 2/10 (caught in at least one run), model explorer 1/10 (caught in at least one run).

## False alarms on the clean application

- Scripted suite: 0 failures of 158 tests.
- random run 1: 0 findings
- random run 2: 0 findings
- random run 3: 0 findings
- llm seed 5: 0 findings
- llm seed 6: 0 findings
- llm seed 7: 0 findings

## Details

### `seat_checked_before_lock`

add_seat reads seat availability before taking the write lock and then claims the seat with an unconditional UPDATE, so two concurrent requests can both succeed and the later one silently takes the seat from the earlier holder (a 50 ms sleep in the faulty branch widens the race window); violates R2.

Scripted suite: `test_checkout::test_a_declined_hold_still_expires_on_time`, `test_races::test_fifty_fans_press_the_same_seat_at_once`, `test_races::test_crowd_on_a_few_hot_seats_never_double_sells`
- random run 1: nothing
- random run 2: nothing
- random run 3: step 29 R2: 5 fans were all told they hold seat A-07
- llm seed 5: nothing
- llm seed 6: step 14 R2: 20 fans were all told they hold seat C-09
- llm seed 7: nothing

### `limit_ignores_owned_tickets`

The four-seat limit counts only seats in the open hold and ignores tickets the account already owns, so an account that bought four seats can hold four more; violates R3.

Scripted suite: `test_limits::test_owned_tickets_count_towards_the_limit`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `hold_expiry_boundary_exclusive`

Expiry uses expires_ms < now instead of <=, so at the exact expiry instant the hold is still active and its seats are not yet available; violates R4.

Scripted suite: `test_checkout::test_a_declined_hold_still_expires_on_time`, `test_time_rules::test_hold_ends_exactly_at_expiry`, `test_time_rules::test_adding_seats_does_not_extend_the_hold`, `test_time_rules::test_paying_after_expiry_is_refused`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `timeout_leaves_hold_paying`

After a gateway timeout the hold is not put back to 'active', so it stays 'paying' for ever: the fan cannot retry, release or change seats, and expiry never frees the seats; violates R6.

Scripted suite: `test_checkout::test_gateway_timeout_charges_nothing_and_keeps_the_seats`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `idempotency_reruns_failed_payment`

A repeated checkout whose first attempt was declined or timed out deletes the stored result and runs the payment again, so the same key can return a different result and charge after a first decline; violates R7.

Scripted suite: `test_checkout::test_repeating_a_declined_checkout_returns_the_same_decline`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `client_sets_amount`

Checkout accepts an amount_cents field from the client and charges that instead of the server's price total; violates R8.

Scripted suite: `test_checkout::test_the_client_cannot_set_the_price`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `remove_seat_from_any_hold`

Releasing a single seat checks only that the seat is held, not that it is in the caller's hold, so a fan with any open hold can release another account's held seat; violates R9 (and R13).

Scripted suite: `test_holds::test_cannot_release_a_seat_you_do_not_hold`, `test_access_control::test_cannot_release_someone_elses_seat`
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `seat_rate_limit_per_session`

The seat-change rate limit is keyed on the session token instead of the account, so signing in again (or using several sessions) gives a fresh allowance and bypasses the limit; violates R10.

Scripted suite: no test failed.
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `map_stale_after_failed_seat_change`

Front end: after a seat request fails (for example 'seat taken') the map is not refreshed, so the seat keeps showing as available until the next 4-second poll; violates R11.

Scripted suite: no test failed.
- random run 1: nothing
- random run 2: nothing
- random run 3: nothing
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

### `release_hold_leaves_seats_held`

Releasing the whole hold closes the hold but its seat update has a wrong status condition that matches nothing, so the seats stay 'held' under a closed hold and never return to sale; violates R13.

Scripted suite: `test_holds::test_releasing_the_whole_hold`, `test_access_control::test_cannot_release_someone_elses_seat`
- random run 1: nothing
- random run 2: nothing
- random run 3: step 30 R13: 1 seat(s) still held under a closed hold
- llm seed 5: nothing
- llm seed 6: nothing
- llm seed 7: nothing

## Cost

Model explorer: 990 model calls, 7095 s of model time on the laptop CPU, no paid service.
