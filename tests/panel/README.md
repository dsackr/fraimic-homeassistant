# Panel browser tests

Regression tests for `custom_components/fraimic/fraimic-panel.js`, driven with
[Playwright](https://playwright.dev) against a real Chromium instance. These
exist because the panel's real bugs live in browser behavior -- DOM/pointer
events, async fetch timing, `<script>`-scope variable shadowing -- that don't
show up from reading the code or from a headless Node syntax check. Two real
examples that prompted this suite:

- `_wallBeginDrag`/`_onWallPointerUp` called `CSS.escape(...)`, but the file
  has a top-level `const CSS` (its stylesheet template string) that shadows
  the global `CSS` object everywhere in the closure -- every drag threw
  immediately and silently failed. Only a real pointerdown/move/up sequence
  in an actual browser reproduces this.
- `_renderWallCanvas()` revoked and re-fetched *every* wall tile thumbnail on
  every render, including tiles nothing changed about. On localhost this is
  instant and invisible; on real network latency it reads as "thumbnails
  clearing" when you edit a single tile.

## Running locally

```sh
cd tests/panel
npm install
npx playwright install chromium   # one-time browser download
npm test
```

`npm run test:headed` runs with a visible browser window, useful when a test
fails and you want to watch it happen. `npm run report` opens the HTML report
from the last run (includes trace files for failures -- `npx playwright
show-trace <path>` from the failure output steps through the exact DOM state
frame by frame).

CI runs this automatically (`.github/workflows/panel-tests.yaml`) on any push
or PR touching `fraimic-panel.js` or this directory.

## How it works

There's no real Home Assistant instance here. `fixtures/harness.html` hosts a
bare `<fraimic-panel>` element and loads the actual `fraimic-panel.js` from
`custom_components/fraimic/`; `fixtures/mock-server.js` is a small in-memory
HTTP server standing in for both HA's WebSocket registries (`hass.callWS`)
and the `/api/fraimic/*` endpoints, so every test gets fresh, isolated
frames/scenes/walls/library state.

**`hass.states` must be populated realistically.** The panel reads
`hass.states[entityId]` directly (e.g. for orientation selects). A real `hass`
object always has this; an incomplete mock without it caused an uncaught
exception mid-way through `_init()` in early drafts of this suite, which
silently skipped every `await` after it (including loading scenes and walls)
and produced misleading, hard-to-explain test failures. `harness.html`'s
`window.__buildMockHass()` builds a consistent `states` map from the frame
list you pass it -- extend that function, not individual tests, if the panel
starts reading a new entity attribute.

`fixtures/panel-page.js` wraps the common flows (open the Walls sub-tab,
create a wall, drag a palette item onto the canvas, open the per-tile image
picker, etc.) as reusable helpers, since driving the shadow DOM and real
`page.mouse` events by hand in every test would bury the intent of each spec.

## Writing a new test

- Prefer extending `fixtures/panel-page.js` over reaching into
  `page.shadowRoot` ad hoc inside a spec -- keeps specs readable as "what
  scenario", not "which selector".
- Every bug fix in the panel should get a regression test here, named after
  the scenario that broke, not the internal function that was wrong (e.g.
  "picking a new image for one tile does not blank ... another tile's
  thumbnail", not "test _pruneWallThumbCache"). Internal refactors shouldn't
  force a test rename.
- If a test's expectation is uncertain, verify it actually catches the bug it
  claims to: temporarily reintroduce the bug, confirm the test fails, then
  restore the fix. A test that passes both with and without the fix isn't
  testing anything.
- Don't add a shared/global mock backend across test files -- each test
  starting its own `createMockServer()` instance (see `test.beforeEach` in
  the existing specs) is what makes tests safe to run in parallel and keeps
  one test's state from leaking into another's.
