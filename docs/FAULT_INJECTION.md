# Seeded faults: testing the tests

A test suite that passes says the application did what the tests checked. It does not say the tests would notice a bug. This experiment measures that, and compares three ways of finding bugs: the scripted suite, an exploratory agent driven by a local language model, and an explorer that chooses at random.

## 1. Method

**The faults.** Ten deliberate bugs live in the application code, each behind a guard such as `if faults.on(settings, "limit_ignores_owned_tickets"):`. A fault is active only when its name appears in the `TICKET_DROP_FAULTS` environment variable. The catalogue, with what each one breaks and which requirement it violates, is in [`app/faults.py`](../app/faults.py).

**Planted blind.** The faults were written by a separate agent that was allowed to read only [BRIEF.md](BRIEF.md) and the files under `app/`. It was told not to open anything under `tests/`, `load/`, `tools/`, `evidence/` or `ai/`, and it reported running the clean suite once (138 passed) without looking at the test files. This matters: if the author of the tests also chooses the bugs, the bugs tend to be the ones the tests already check, and the detection rate is flattering.

**Clean behaviour preserved.** With no fault enabled, every guard is skipped. The diff was reviewed line by line, and the full suite passes on the clean application before any fault run.

**Scripted suite.** `tools/fault_matrix.py` runs the API, security, concurrency and browser tests once per fault. A fault counts as caught when at least one test fails.

**Explorers.** `tools/run_explorers.py` gives each explorer a fresh server per run, with the sale opening 60 seconds after start, and the same budget of actions. After every action the same rule checks run: no server errors; no seat claimed by two fans at once; no account over four seats; money charged equal to ticket value; no seats stuck under a closed hold; no hold still active at or after its expiry; no hold before the sale opens; no access to another account's seats or tickets; a repeated payment key returning its first result; rapid seat changes eventually rate limited; and the seat map matching the database. The model explorer chooses each action from the product rules and the recent history, and states a reason. The random explorer chooses uniformly from the same actions with random parameters, and runs three times with different seeds. Runs on the clean application measure false alarms.

**Fairness of the checks.** The explorer's rule checks were designed from the requirements before the fault catalogue existed. The author saw the catalogue while finishing the explorer code; the list of checks was kept exactly as designed, and this note records that the author had seen it.

## 2. Results

The table and per-fault details are generated from the saved runs into [evidence/faults/REPORT.md](../evidence/faults/REPORT.md) by `tools/build_reports.py`. Raw data: [scripted.json](../evidence/faults/scripted.json), [explorers.json](../evidence/faults/explorers.json), and every model decision with its stated reason in [explorer_transcripts.jsonl](../evidence/ai/explorer_transcripts.jsonl).

| Approach | Faults caught (at least once) | False alarms on the clean app |
|---|---|---|
| Scripted suite (158 tests at the time) | 8 of 10 | 0 |
| Scripted suite after closing the two gaps (159 tests at the time) | 10 of 10 | 0 |
| Random explorer, 3 seeds | 2 of 10 | 0 |
| Local model explorer (llama3.2), 3 seeds | 1 of 10 | 0 |

The per-fault table is in [evidence/faults/REPORT.md](../evidence/faults/REPORT.md); the follow-up for the two gap-closing changes is in [scripted-after-gap-tests.json](../evidence/faults/scripted-after-gap-tests.json).

The report names tests as they were at the time of the run. Two have changed since: `test_checkout::test_repeating_a_declined_checkout_returns_the_same_decline` is now `test_repeating_a_failed_checkout_returns_the_same_failure`, which covers every failure kind, and `test_holds::test_cannot_release_a_seat_you_do_not_hold` was removed as a duplicate of `test_access_control::test_cannot_release_someone_elses_seat`, which caught the same fault.

### What the results mean

**The scripted suite caught 8 of 10.** The two it missed share a cause: each test checked the rule from only one angle.

- `seat_rate_limit_per_session` keyed the rate limit on the session instead of the account. The rate-limit test used one session, so a fan who signs in twice was never tried.
- `map_stale_after_failed_seat_change` stopped the map refreshing after a failed click. The browser test did check the map, but it waited up to five seconds, longer than the page's own four-second refresh, so the refresh quietly repaired the bug before the check gave up.

Both gaps were closed after the experiment with one new test and one tightened assertion: a new test checks that a fan signed in twice still hits the limit (158 to 159 tests), and the existing browser test now requires the page to re-read the map within 1.5 seconds of the refusal instead of waiting up to the default 5 seconds. Each changed test fails with its fault switched on and passes without it. The experiment's result stays 8 of 10; the follow-up is recorded separately.

**One fault was caught for an unexpected reason.** `seat_checked_before_lock` was meant to be a race: it reads the seat outside the lock and adds a 50 ms pause. The concurrency tests caught it as intended, but so did an ordinary one-at-a-time test about expiry, because the early read happens before overdue holds are released, so a seat whose hold had just expired still looked taken. Real bugs often break more than their author intended.

**The random explorer caught 2 of 10.** Its successes were genuine: a crowd of five fans all told they held seat A-07 (the race), and a seat left held under a closed hold (the release bug). Both came from the third seed only, which shows how much one random run depends on luck.

**The local model explorer caught 0 of 10 with its first seed.** Its transcript shows why. It bought seat C-09 at step 4, then spent most of its remaining 26 actions trying to hold C-09 again, or sending crowds of fans at C-09, even though every answer said the seat was taken. The race fault can only show on a free seat, so it was never exercised. All eleven runs with that seed made exactly the same 30 choices, because a fixed seed and identical answers from the application produce identical model output. That was one exploration path, repeated eleven times.

**Two more seeds, for a fair comparison.** The random explorer had three seeds per fault, so the model was given two more (6 and 7). With seed 6 it caught the race: twenty fans were all told they held seat C-09, because in that run it sent the crowd while C-09 was still free. Seeds 6 and 7 each produced only two distinct action sequences across their eleven runs, diverging only where a fault changed an answer, so the 33 model runs explored about five genuinely different paths. Final count with three seeds each: random 2 of 10, model 1 of 10, no false alarms from either on the clean application. The model runs used 990 calls and about two hours of laptop CPU, at no monetary cost.

**What to take from it.** On this application, written tests that target specific rules beat both exploration methods by a wide margin. A small local model, given a list of actions and the rules, did not use the feedback it received; random choice with the same number of seeds did slightly better, 2 against 1, which is too few to call a real difference. This says something about a 3-billion-parameter model on a laptop with this prompt. It does not say what a larger model, a better prompt, or a planner that tracks which seats are free could do; those are the obvious next experiments. The prompt was not changed after seeing these results, because tuning it to the planted faults would make the comparison meaningless.


## 3. Limits of this experiment

- Ten faults is a small sample, and all of them were written by one agent with one idea of what a realistic bug looks like.
- The race fault includes a 50 ms sleep in its faulty branch to make the race window reliably reachable. Without it, the bug is real but would be caught less often.
- Each explorer had three seeds per fault. With a fixed seed the model repeats itself whenever the application answers the same way, so three seeds gave about five distinct paths, not 33.
- The explorers act only through the API. A fault that exists only in the browser cannot be found by them.
- The scripted suite was written before the faults existed, by an author who had not seen them, and was not changed during the experiment. The gap-closing test and assertion were added afterwards and are reported separately.
