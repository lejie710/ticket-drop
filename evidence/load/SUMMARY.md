# Sale-opening spike

200 simulated fans, all started within one second, for 60 seconds, against one local server process on the development laptop. Run at 2026-11-04 06:08 UTC.

| Endpoint | Requests | Failures | Median ms | p95 ms | p99 ms | Max ms | Avg req/s |
|---|---|---|---|---|---|---|---|
| GET /api/seats | 451 | 0 | 3100 | 4600 | 4800 | 4919 | 7.5 |
| POST /api/checkout | 38 | 0 | 1800 | 5300 | 9500 | 9547 | 0.6 |
| POST /api/hold/seats | 377 | 0 | 3000 | 6200 | 8700 | 11111 | 6.3 |
| login | 200 | 0 | 1400 | 3200 | 3300 | 3268 | 3.3 |
| Aggregated | 1066 | 0 | 2900 | 4700 | 7500 | 11111 | 17.8 |

Failures count only server errors and broken connections. Refusals such as seat taken or limit reached are correct answers.

## Database checked after the run

| Check | Result |
|---|---|
| tickets issued | 59 |
| seats sold twice | 0 |
| sold seats without ticket | 0 |
| tickets on unsold seats | 0 |
| accounts over limit | 0 |
| charged cents | 1705200 |
| ticket value cents | 1705200 |
| payments left pending | 0 |
| money matches tickets | True |
| passed | True |

Overall: PASS
