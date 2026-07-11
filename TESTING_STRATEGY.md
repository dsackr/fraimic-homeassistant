# Testing strategy

Status: Living document. Tracks how this repo tests its Key Product Flows
(see [docs/KEY_PRODUCT_FLOWS.md](docs/KEY_PRODUCT_FLOWS.md)) and what's
left to cover.

## 1. Why this exists

Until now, `custom_components/fraimic/` (the Python backend, ~9,100 lines)
had zero automated tests — the only suite was Playwright coverage for the
frontend panel (`tests/panel/`). This doc records the testing standard the
project now holds itself to, and gives future work (mine or a
contributor's) a checkpoint tracker instead of a from-scratch decision
every time backend coverage comes up.

## 2. Tooling & strategy

- **Backend** (`custom_components/fraimic/*.py`): `pytest` +
  [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
  (PHACC), which vendors a real Home Assistant core and provides the `hass`
  fixture, `MockConfigEntry`, and `aioclient_mock`. Tests live under
  `tests/python/`; shared fixtures are in `tests/python/conftest.py`.
- **Frontend** (`fraimic-panel.js`): Playwright, unchanged — see
  `tests/panel/README.md`.
- One suite per language, not split further — pure-logic modules
  (`image_converter.py`, `frame_types.py`, `helpers.render_spec_for_entry`)
  run as plain pytest functions inside the same backend suite rather than
  a separate toolchain.
- **PHACC version pin**: `requirements-test.txt` pins
  `pytest-homeassistant-custom-component==0.13.316`, which vendors Home
  Assistant core `2026.2.3`. `manifest.json` declares no minimum HA
  version, so this pin is the de facto "validated against this HA release"
  statement. Bump it deliberately (not automatically) when picking up a
  newer core release, and skim PHACC's changelog for fixture-breaking
  changes when doing so.
- **Local setup**: the backend suite requires **Python 3.13+** (matches
  current HA core's minimum) — noticeably newer than whatever ships as
  the system `python3` on most machines. Create a venv against a 3.13+
  interpreter and `pip install -r requirements-test.txt`, then
  `python -m pytest tests/python/ --cov=custom_components.fraimic --cov-report=term-missing`.

## 3. Where test results live

- **CI**: `.github/workflows/python-tests.yaml` runs the backend suite on
  every push/PR touching `custom_components/fraimic/**.py` or
  `tests/python/**`, writes a coverage summary to the GitHub Actions job
  summary (visible directly in the PR checks tab — no third-party
  coverage service), and uploads the full HTML coverage report as a
  build artifact on every run.
- `.github/workflows/panel-tests.yaml` (pre-existing) does the same for
  the Playwright suite, uploading a report on failure.
- `.github/workflows/security-scan.yaml` publishes bandit + pip-audit
  results to the job summary (see §5).

## 4. Post-release KPF smoke test

`scripts/smoke_test.py` exercises the REST/WS-shaped KPFs (config entries
present, scenes list/send, schedules list, walls list, library list)
against a real, running Home Assistant instance. It's a manual,
maintainer-run script — not wired into CI, since there's no persistent
test frame/instance available to a pipeline. Run it after a release:

```
FRAIMIC_HAPI_URL=http://your-test-ha:8123 FRAIMIC_HAPI_TOKEN=... python3 scripts/smoke_test.py
```

Flows that need eyeballing real hardware (image color accuracy, physical
rotation/orientation on a panel) aren't script-checkable — those stay a
manual checklist item: send one image through each of the Auto/Portrait/
Landscape orientation paths to a real frame and confirm it displays
right-side-up and correctly cropped.

## 5. Load testing & SAST — what this repo does instead of a corporate-scale answer

This is a single-maintainer, `iot_class: local_polling` HA integration —
there's no staging/production traffic concept and no dedicated security
scanning platform provisioned for it. Rather than skip these entirely:

- **Load testing substitute**: `tests/python/coordinator/test_coordinator_concurrency.py`
  exercises N coordinators (frames) polling and sending concurrently
  against the mocked HTTP layer, confirming per-frame state
  (`pending_send`, failure counters) stays isolated instead of racing on
  shared state. This is the nearest equivalent to load evidence for a
  household with several frames polling/sending at once — not a
  throughput benchmark, since there's no server tier to benchmark.
- **SAST substitute**: `.github/workflows/security-scan.yaml` runs
  `bandit` (static analysis) and `pip-audit` (dependency vulnerability
  scanning against `manifest.json`'s declared requirements), publishing
  results to the job summary on every push/PR plus a weekly scheduled
  run. **Report-only, not a merge gate** — a human reviews findings
  rather than the pipeline auto-blocking on them. Several of bandit's
  current findings are known-benign (an MD5 hash used only as a cache
  ETag key, OAuth token URLs its heuristics mistake for hardcoded
  secrets); auto-blocking on those would just train everyone to ignore
  the job. If that changes (real findings show up, or this project wants
  a harder gate later), tighten this workflow then.

## 6. Coverage target

Declared, not aspirational-on-day-one: **ratchet upward per phase** (see
§7) rather than picking one number up front. Today's baseline after
Phases 0-3:

| Module | Coverage |
|---|---|
| `select.py` | 100% |
| `intent.py` | 100% |
| `const.py` | 100% |
| `sensor.py` | 98% |
| `coordinator.py` | 89% |
| `image_converter.py` | 88% |
| `frame_types.py` | 96% |
| `config_flow.py` | 84% |
| `helpers.py` | 77% |
| `__init__.py` | 76% |
| Overall (`custom_components.fraimic`) | ~46% (Phases 4-5 — the Store-backed managers and library backends — still open) |

Once Phase 4-5 land, target **65% overall**, enforced via
`pytest-cov --cov-fail-under=65` in CI. Not set as a hard gate yet since
enforcing it before the remaining phases exist would just fail every
build.

## 7. Phase checkpoint tracker

Maps to [docs/KEY_PRODUCT_FLOWS.md](docs/KEY_PRODUCT_FLOWS.md)'s numbered
flows.

| Phase | Scope | KPFs | Status |
|---|---|---|---|
| 0 | pytest infra: PHACC pin, `conftest.py` fixtures, coverage config, CI workflow | — | **Done** |
| 1 | Pure-logic, highest silent-failure risk: image conversion byte pipeline, render-spec rotation math, frame-type registry | 7, 22, 23 | **Done** |
| 2 | Coordinator: polling, IP self-healing, queue-on-sleep send/flush, concurrency | 3, 4 | **Done** |
| 3 | Config flow + setup lifecycle: discovery wizard, options flow, services, voice intent, entities, onboarding backend, `async_setup_entry`/`async_unload_entry` | 1, 2, 5, 6, 21, 24, 25 | **Done** |
| 4 | Store-backed managers: scenes, scene packs + widget scheduling, walls, schedules recurrence math | 16, 17, 18, 19, 20 | Planned |
| 5 | Library: local/cloud backends, OAuth, backfill, crop, albums, HTTP views | 8, 9, 10, 11, 12, 13, 14, 15 | Planned |

Each phase is independently landable — a future session can pick up any
one without redoing the others. Fixtures added for a later phase (OAuth
token-exchange stubs, subprocess mocking, freezegun time control) should
land in `tests/python/conftest.py` alongside the phase that first needs
them, following the pattern set in Phase 0-2.
