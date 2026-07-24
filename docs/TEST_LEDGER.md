# Test ledger

Append-only, durable record of test-suite runs against `main`. CI appends
one row per suite per push (see the "Record result in the test ledger"
step in `.github/workflows/python-tests.yaml` and `panel-tests.yaml`);
rows are committed back to this file with `[skip ci]`, so recording never
triggers more CI. Failures are recorded too — a red row is the point of
having a ledger.

Notes on reading it:
- Both test workflows are path-filtered, so a push that touches neither
  the backend nor the frontend (docs, CI) legitimately has no row.
- `Coverage` is the backend suite's overall `custom_components.digital_frames`
  percentage; the Playwright suite doesn't measure coverage.
- Rows marked `local` were recorded by hand before CI recording existed
  (or for suites run outside CI); everything after 2026-07-12 should come
  from CI.

| Date (UTC) | Commit | Suite | Result | Detail | Coverage | Source |
|---|---|---|---|---|---|---|
| 2026-07-12 | 7f34f0e | backend-pytest | pass | 253 passed | 64% | CI + local |
| 2026-07-12 | 7f34f0e | panel-playwright | pass | 132 passed | — | CI + local |
| 2026-07-12 | 4489da6 | panel-playwright | pass | 133 passed | — | CI + local |
| 2026-07-13 | 9520461 | panel-playwright | success | 133 passed | — | CI |
| 2026-07-13 | 9520461 | backend-pytest | success | 253 passed in 66.99s (0:01:06) | 64% | CI |
| 2026-07-13 | 9520461 | smoke-hapi | pass | 8/8 KPF checks vs hapi.dalesackrider.com (v0.12.87, real 13.3" frame at .117; card fields verified live) | — | local |
| 2026-07-13 | 7b545ea | panel-playwright | success | 133 passed | — | CI |
| 2026-07-13 | 6d9040b | panel-playwright | success | 134 passed | — | CI |
| 2026-07-14 | a468e13 | backend-pytest | success | 258 passed in 67.22s (0:01:07) | 64% | CI |
| 2026-07-14 | b49a3ca | panel-playwright | success | 135 passed | — | CI |
| 2026-07-14 | ed47648 | backend-pytest | success | 258 passed in 67.06s (0:01:07) | 64% | CI |
| 2026-07-14 | 4c7dbb4 | panel-playwright | success | 136 passed | — | CI |
| 2026-07-14 | 4c7dbb4 | backend-pytest | success | 260 passed in 68.79s (0:01:08) | 64% | CI |
| 2026-07-17 | 08b8c29 | backend-pytest | success | 261 passed in 68.88s (0:01:08) | 64% | CI |
| 2026-07-17 | 2ffe2f0 | backend-pytest | success | 263 passed in 68.86s (0:01:08) | 64% | CI |
| 2026-07-17 | 7c13c1a | panel-playwright | success | 136 passed | — | CI |
| 2026-07-17 | 7c13c1a | backend-pytest | success | 266 passed in 67.31s (0:01:07) | 64% | CI |
| 2026-07-17 | 51fb400 | backend-pytest | success | 266 passed in 66.81s (0:01:06) | 64% | CI |
| 2026-07-18 | aea1257 | backend-pytest | success | 267 passed in 68.54s (0:01:08) | 64% | CI |
| 2026-07-18 | 057393b | backend-pytest | success | 267 passed in 68.07s (0:01:08) | 64% | CI |
| 2026-07-19 | ddef7f0 | backend-pytest | success | 282 passed in 47.52s | 64% | CI |
| 2026-07-19 | 71ceb67 | backend-pytest | success | 285 passed in 67.80s (0:01:07) | 64% | CI |
| 2026-07-19 | aa7f2e0 | backend-pytest | success | 292 passed in 67.46s (0:01:07) | 64% | CI |
| 2026-07-19 | d32cbda | panel-playwright | success | 136 passed | — | CI |
| 2026-07-19 | 14b227a | panel-playwright | success | 136 passed | — | CI |
| 2026-07-19 | 14b227a | backend-pytest | success | 295 passed in 72.67s (0:01:12) | 62% | CI |
| 2026-07-19 | 02a3799 | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | 22c6011 | backend-pytest | success | 298 passed in 72.10s (0:01:12) | 62% | CI |
| 2026-07-19 | 65dd95f | backend-pytest | success | 302 passed in 70.97s (0:01:10) | 61% | CI |
| 2026-07-19 | 2836ca7 | backend-pytest | success | 308 passed in 57.51s | 62% | CI |
| 2026-07-19 | 59e5ef0 | backend-pytest | success | 309 passed in 48.15s | 62% | CI |
| 2026-07-19 | 50db356 | backend-pytest | success | 311 passed in 71.31s (0:01:11) | 62% | CI |
| 2026-07-19 | 5ffd32d | backend-pytest | failure | 3 failed, 311 passed in 71.86s (0:01:11) | 62% | CI |
| 2026-07-19 | 595c090 | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | 595c090 | backend-pytest | failure | 3 failed, 313 passed in 73.64s (0:01:13) | 61% | CI |
| 2026-07-19 | 7fb9599 | backend-pytest | failure | 3 failed, 317 passed in 71.69s (0:01:11) | 62% | CI |
| 2026-07-19 | 8a6d09d | backend-pytest | success | 320 passed in 72.38s (0:01:12) | 62% | CI |
| 2026-07-19 | 5641d60 | backend-pytest | success | 326 passed in 70.75s (0:01:10) | 61% | CI |
| 2026-07-19 | cc4909d | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | cc4909d | backend-pytest | success | 328 passed in 72.53s (0:01:12) | 61% | CI |
| 2026-07-19 | 2ac25ab | backend-pytest | success | 329 passed in 73.20s (0:01:13) | 62% | CI |
| 2026-07-19 | b85803b | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | b85803b | backend-pytest | success | 339 passed in 72.02s (0:01:12) | 62% | CI |
| 2026-07-19 | 0907f9d | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | 0907f9d | backend-pytest | success | 342 passed in 71.85s (0:01:11) | 62% | CI |
| 2026-07-19 | 5d49b3d | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | 5d49b3d | backend-pytest | success | 344 passed in 74.25s (0:01:14) | 62% | CI |
| 2026-07-19 | 3686ab2 | backend-pytest | success | 345 passed in 59.60s | 62% | CI |
| 2026-07-19 | 72ee985 | backend-pytest | success | 348 passed in 74.94s (0:01:14) | 62% | CI |
| 2026-07-19 | e2edd47 | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | e2edd47 | backend-pytest | success | 348 passed in 72.98s (0:01:12) | 62% | CI |
| 2026-07-20 | b7aad44 | panel-playwright | success | 141 passed | — | CI |
| 2026-07-20 | b7aad44 | backend-pytest | success | 363 passed in 74.03s (0:01:14) | 63% | CI |
| 2026-07-20 | b3c9daf | panel-playwright | success | 141 passed | — | CI |
| 2026-07-20 | b3c9daf | backend-pytest | success | 366 passed in 77.58s (0:01:17) | 62% | CI |
| 2026-07-20 | 136d13e | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 136d13e | backend-pytest | success | 366 passed in 74.00s (0:01:13) | 64% | CI |
| 2026-07-20 | 6318eb0 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 6318eb0 | backend-pytest | success | 369 passed in 75.60s (0:01:15) | 64% | CI |
| 2026-07-20 | 172e104 | backend-pytest | success | 370 passed in 77.45s (0:01:17) | 64% | CI |
| 2026-07-20 | 63948d0 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | b97e382 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 63948d0 | backend-pytest | success | 371 passed in 75.97s (0:01:15) | 64% | CI |
| 2026-07-21 | 4a58d08 | panel-playwright | success | 140 passed | — | CI |
| 2026-07-21 | 4a58d08 | backend-pytest | success | 403 passed in 78.05s (0:01:18) | 64% | CI |
| 2026-07-24 | b7ed014 | panel-playwright | success | 151 passed | — | CI |
