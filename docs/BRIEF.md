# Ticket Drop: approved brief

Approved by the owner on 3 November 2026. This file records the agreed product contract. Implementation detail lives in [DESIGN.md](DESIGN.md); test strategy lives in [TEST_PLAN.md](TEST_PLAN.md).

## Purpose

Ticket Drop is a concert ticket sale application built to be tested thoroughly. The product question it answers is simple: when many fans press Buy at the same moment, can anyone be sold the same seat twice, lose seats they were holding, or pay without getting tickets?

It is a portfolio project for software quality engineering (SDET). The application is deliberately small; the depth is in how its behaviour is specified, tested, attacked, measured and signed off.

## Intended user

A fan buying up to four seats for one concert on a laptop or phone. A second audience is an engineer reviewing the project, who should be able to run every check locally.

## Version 1 scope

- One concert, one hall, a seat map of about 500 seats in three price categories.
- Seats are held for five minutes, then paid for or released. Expired holds return to sale.
- At most four seats per account.
- A mock payment service that succeeds, declines, or times out depending on the test card.
- Seeded demo accounts with token login. No registration.
- A scheduled sale opening time and request rate limits.
- A My tickets page.

## Excluded from version 1

Real payment, registration and password reset, multiple events, a waiting-room queue, email, a native mobile app, an admin console, and public hosting of the application.

## Requirements

Each requirement has an identifier that tests refer to.

| ID | Requirement |
|---|---|
| R1 | Seats cannot be held before the sale opens. The opening instant itself is open. |
| R2 | A seat is held or sold by at most one account at any time, including under concurrent requests. |
| R3 | An account may hold and own at most four seats in total. A fifth seat is refused. |
| R4 | A hold lasts exactly 300 seconds from its creation. Adding seats does not extend it. At the expiry instant the hold has ended and its seats are available again. |
| R5 | A successful payment issues one ticket per held seat, marks those seats sold and closes the hold. |
| R6 | A declined or timed-out payment issues no tickets and charges nothing; the seats stay held until the hold expires, so the fan can retry. |
| R7 | Repeating a checkout with the same idempotency key never charges twice and returns the first result. |
| R8 | The amount charged is computed by the server from its own prices. A client cannot set it. |
| R9 | Fans can see and change only their own holds and tickets. Requests without a valid token are refused. |
| R10 | Login and seat-hold requests are rate limited and answered with 429 and a Retry-After header when exceeded. |
| R11 | The seat map shows each seat as available, taken or yours, consistent with the server. |
| R12 | Malformed input is refused without changing any state. |
| R13 | A fan can release one held seat or the whole hold; released seats are available immediately. |
| R14 | Under a burst of buyers at sale opening the service returns no server errors and sells no seat twice. Latency is measured and reported as an observation, not promised as a service level. |

## Quality deliverables

- A risk-based test plan linking every requirement to its checks.
- Automated API, browser (Playwright), concurrency, security and load (Locust) tests.
- Seeded faults, off by default, to measure which bugs each testing approach catches.
- An AI testing layer using a local model: generated test data, and an exploratory agent compared with the scripted suite and a random baseline.
- A defect log, a verification record and a release sign-off report.
- A learning companion (Markdown source, Word and PDF) and a static showcase page prepared for GitHub Pages.

## Constraints

Local operation on Windows with Python 3.12. No paid services. The AI layer uses the locally installed Ollama `llama3.2` model. The repository stays private until the owner decides otherwise; nothing is pushed or deployed automatically.
