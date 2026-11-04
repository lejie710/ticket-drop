# Sale-opening spike

200 simulated fans, all started within one second, for 60 seconds, against one local server process on the development laptop. Run at 2026-11-03 17:07 UTC.

| Endpoint | Requests | Failures | Median ms | p95 ms | p99 ms | Max ms | Avg req/s |
|---|---|---|---|---|---|---|---|
| GET /api/seats | 476 | 0 | 3200 | 5400 | 5600 | 5766 | 7.9 |
| POST /api/checkout | 54 | 0 | 2200 | 7600 | 12000 | 11583 | 0.9 |
| POST /api/hold/seats | 430 | 0 | 3200 | 6600 | 11000 | 14849 | 7.2 |
| login | 200 | 0 | 1300 | 3200 | 3400 | 3383 | 3.3 |
| Aggregated | 1160 | 0 | 2900 | 5400 | 9000 | 14849 | 19.3 |

Failures count only server errors and broken connections. Refusals such as seat taken or limit reached are correct answers.

## Database checked after the run

| Check | Result |
|---|---|
| tickets issued | 60 |
| seats sold twice | 0 |
| sold seats without ticket | 0 |
| tickets on unsold seats | 0 |
| accounts over limit | 0 |
| charged cents | 1726000 |
| ticket value cents | 1726000 |
| payments left pending | 0 |
| money matches tickets | True |
| passed | True |

Overall: PASS
