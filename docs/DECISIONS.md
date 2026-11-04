# Decision log

Why things are the way they are. Product decisions were made by the project owner, Le Jie Tan; engineering decisions were made during implementation with AI assistance and reviewed against measured results.

## Product decisions (owner)

| Decision | Alternatives considered | Reason |
|---|---|---|
| Build a concert ticket sale | A voucher service, a claims tracker | A relatable problem with a clear failure question: can one seat be sold twice? Its rules are rich in boundaries and concurrency, which is what a quality-engineering project needs |
| Version 1 scope: one event, holds, limit, mock payment, demo accounts, rate limits, My tickets | Registration, multiple events, waiting room, email, admin | Every included feature gives a specific kind of test something real to check; the exclusions add code without adding test depth |
| Approve a visual mockup before building | Build first, style later | A concrete mockup made the visual direction checkable before any code |
| AI layer on a local model (llama3.2 through Ollama) | A paid hosted model | Free, offline and reproducible; weaker results are reported as they are |
| Showcase as a code repository plus a static page; no hosted app | Host the live app | Load tests must not be aimed at a free host, and the evidence lives in the code and reports |

## Engineering decisions

| Decision | Alternatives | Reason and trade-off |
|---|---|---|
| Python, FastAPI, SQLite | Node, PostgreSQL | One language across app and tests; nothing to install on Windows. SQLite has one writer at a time, which makes correctness easier and limits throughput (DEF-002) |
| `BEGIN IMMEDIATE` plus a conditional `UPDATE` for seat claims | Optimistic version numbers, application locks | The write lock makes check-then-claim atomic; the conditional update still refuses a second claim on its own. Simple to explain and to test |
| Three-step checkout with a `paying` hold state | Call the gateway inside the transaction | Keeps the slow gateway call out of the lock so other fans are not blocked; the `paying` state stops expiry from reselling seats mid-payment. Cost: a crash between the charge and recording its outcome needs reconciliation that version 1 lacks |
| Store the full response with each payment | Store only the outcome | A repeated key returns exactly the same status and body, which is what a retrying client needs |
| Idempotency keys scoped to the account | Global keys | One fan's key can never reveal or replay another fan's payment |
| Another fan's ticket answers 404, not 403 | 403 Forbidden | Does not confirm that the ID exists |
| An injectable clock | Sleeping in tests, patching `time` | Exact boundary tests (299 999 and 300 000 ms) that run instantly |
| A test-only clock route behind an environment flag | No live-server time control | Browser and explorer tests can expire a hold without waiting five minutes; a security test proves the route is absent by default |
| Read endpoints take the write lock only when a hold is overdue | Always expire on read | Reads stop queueing behind writes. Measured gain was small (DEF-002) and is reported as such |
| Plain JavaScript, no framework | React or similar | The page is small; a framework would add build tooling without adding any behaviour worth testing |
| Playwright with the installed Chrome | Selenium, a downloaded browser | Assertions that wait for the page to settle, and locators by role and label as a user or screen reader finds things; drives the installed Chrome, so no separate browser download |
| Locust for load | k6 | Python like everything else; installs from PyPI with no separate binary |
| A rule oracle judges generated test data | Trust the model's own labels | The model labelled 8 of its 52 inputs wrongly. An input generator must not be its own judge |
| Seeded faults planted by a separate agent that never saw the tests | Plant them myself | Otherwise the detection rate would measure what the author already knew to check |
| The explorer's rule checks fixed before the fault list existed | Adjust checks after seeing faults | Same reason: a fair comparison between scripted, random and model-driven exploration |
| A random-choice explorer as a baseline | Compare the model only with the scripted suite | Separates "the checks found it" from "the chooser led the checks to it" |
