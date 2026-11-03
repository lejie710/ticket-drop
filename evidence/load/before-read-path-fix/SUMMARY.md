# Sale-opening spike

200 simulated fans, all started within one second, for 60 seconds, against one local server process on the development laptop. Run at 2026-11-03 15:08 UTC.

| Endpoint | Requests | Failures | Median ms | p95 ms | p99 ms | Max ms | Req/s |
|---|---|---|---|---|---|---|---|
| GET /api/seats | 524 | 0 | 890 | 3300 | 6100 | 9412 | 39.3 |
| POST /api/checkout | 66 | 0 | 740 | 1100 | 2000 | 1977 | 4.9 |
| POST /api/hold/seats | 456 | 0 | 1000 | 2200 | 5400 | 8481 | 34.2 |
| login | 199 | 0 | 1500 | 4200 | 6400 | 7660 | 14.9 |
| Aggregated | 1245 | 0 | 970 | 3000 | 6100 | 9412 | 93.3 |

Failures count only server errors and broken connections. Refusals such as seat taken or limit reached are correct answers.

## Database checked after the run

| Check | Result |
|---|---|
| tickets issued | 92 |
| seats sold twice | 0 |
| sold seats without ticket | 0 |
| tickets on unsold seats | 0 |
| accounts over limit | 0 |
| charged cents | 2719600 |
| ticket value cents | 2719600 |
| payments left pending | 0 |
| money matches tickets | True |
| passed | True |

Overall: PASS
