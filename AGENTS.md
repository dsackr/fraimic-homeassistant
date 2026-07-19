# Instructions for AI agents (and humans) working in this repo

These rules are binding for every change made in this repository, whether
authored by a human or an AI coding agent. `CLAUDE.md` points here; if your
tool reads a different instructions file, treat this one as authoritative.

## The two non-negotiables for feature work

Any change that adds or alters **user-facing behavior** — a new capability,
a new UI surface or action, a changed flow, a fixed behavioral bug — must
land in the same commit/PR with BOTH of the following. Neither is optional,
and neither may be deferred to "a follow-up":

1. **A Key Product Flows update.** `docs/KEY_PRODUCT_FLOWS.md` is the
   source of truth for what "the product doing its job" means. Either add
   a new KPF entry or amend the affected one(s), keeping every section
   accurate: the description, **Entry points** (file + function names),
   **If it silently breaks** (what the end user actually experiences), and
   **Test status** (which suites/files cover it now). New entries are
   appended with the next number — KPF numbers are stable identifiers
   referenced from code comments and test docstrings, so never renumber
   existing entries. If your change closes a documented Gap, say so; if it
   introduces one, document the Gap honestly rather than omitting it.

2. **Tests that exercise the feature.** Define what "this works" means for
   the flow and encode it:
   - **Backend** (Python under `custom_components/digital_frames/`): pytest in
     `tests/python/` (PHACC provides `hass`, `MockConfigEntry`; shared
     fixtures in `tests/python/conftest.py`). Run from the repo root:
     `.venv/bin/python -m pytest -q`.
   - **Frontend** (`digital-frames-panel.js`, `digital-frames-card.js`): Playwright in
     `tests/panel/` against the mock server
     (`tests/panel/fixtures/mock-server.js`). The sidebar panel mounts via
     `fixtures/harness.html`; the Lovelace card via
     `fixtures/card-harness.html`. Run: `cd tests/panel && npx playwright test`.
   - The KPF entry's **Test status** line and the tests you ship must
     agree — never claim coverage the suite doesn't actually have.

A pure refactor with no behavior change doesn't need a new KPF, but if it
moves entry points, update the KPF entries that name them. Docs-only and
CI-only changes are exempt.

Before finishing any task, re-read your diff and ask: "did user-facing
behavior change?" If yes and there's no KPF diff and no test diff alongside
it, the work is not done.

## Repo-specific rules that will bite you

- **Never hand-edit the version** in `manifest.json`. Every push to `main`
  auto-bumps it, tags, and publishes a release. Pushing = releasing.
- Expect the version-bump automation to reject a push with a fetch-first
  error occasionally; rebase and push again.
- Run backend tests from the **repo root** (pytest's `testpaths` points at
  `tests/python`; running from inside `tests/` breaks conftest discovery).
- `scripts/verify_packing.py` exists for manual byte-identity checks when
  touching either image packer — see KPF 7.

## Where things are documented

- `docs/KEY_PRODUCT_FLOWS.md` — the KPF catalog (read it before changing
  behavior; your change almost certainly touches one).
- `docs/FRAME_PORT.md` — design note for the multi-driver FramePort
  contract (core vs Fraimic driver, capabilities, conversion ownership).
  Design-only until implemented; read before generalizing beyond the
  Fraimic protocol family.
- `docs/TEST_LEDGER.md` — the durable, append-only record of test runs on
  `main`. CI appends rows automatically on push; if you run a suite by hand
  for a change that CI's path filters won't cover, append a `local` row
  yourself. Never rewrite or delete existing rows.
- `TESTING_STRATEGY.md` — the testing standard and phase/checkpoint tracker.
- `CONTRIBUTING.md` — codebase layout and dev-environment setup.
