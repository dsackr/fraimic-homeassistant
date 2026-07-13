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
- `Coverage` is the backend suite's overall `custom_components.fraimic`
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
