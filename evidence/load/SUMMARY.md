# Sale-opening spike

200 simulated fans, all started within one second, for 60 seconds, against one local server process on the development laptop. Run at 2026-11-03 15:11 UTC.

| Endpoint | Requests | Failures | Median ms | p95 ms | p99 ms | Max ms | Avg req/s |
|---|---|---|---|---|---|---|---|
| GET /api/seats | 630 | 0 | 2300 | 4900 | 5200 | 5220 | 10.5 |
| POST /api/checkout | 93 | 0 | 1600 | 4900 | 7400 | 7445 | 1.6 |
| POST /api/hold/seats | 634 | 0 | 2200 | 5900 | 9200 | 12123 | 10.6 |
| login | 200 | 0 | 1500 | 3600 | 3700 | 3849 | 3.3 |
| Aggregated | 1557 | 0 | 2100 | 5100 | 7800 | 12123 | 25.9 |

Failures count only server errors and broken connections. Refusals such as seat taken or limit reached are correct answers.

## Database checked after the run

| Check | Result |
|---|---|
| tickets issued | 123 |
| seats sold twice | 0 |
| sold seats without ticket | 0 |
| tickets on unsold seats | 0 |
| accounts over limit | 0 |
| charged cents | 3590400 |
| ticket value cents | 3590400 |
| payments left pending | 0 |
| money matches tickets | True |
| passed | True |

Overall: PASS
