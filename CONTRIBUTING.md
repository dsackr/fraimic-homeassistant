# Contributing to Fraimic for Home Assistant

Thanks for your interest in contributing. This is a custom HACS integration for Fraimic e-ink frames — it talks to the frame's local HTTP API and converts images to Spectra 6 binary format on the fly.

## How it works (the short version)

- **`coordinator.py`** — polls each frame's `/api/info` endpoint on a schedule; handles DHCP autodiscovery and IP self-healing
- **`library.py`** — pluggable image storage (local HA storage, Dropbox, Google Drive); stores a JSON manifest + original images. Uploading only stores the original and returns immediately; per-resolution `.bin` generation for every configured frame size runs afterward in a background task (`LibraryManager._schedule_backfill`/`_async_backfill_worker`) so a bulk operation (a multi-file upload, a scene pack install) isn't one long blocking request, and `async_get_bin_for_send` still generates on the fly if a send happens before the background pass gets to it. Dropbox additionally supports "discovery" (`LibraryBackend.supports_discovery`): files dropped into `/fraimic_library/inbox` outside the app get adopted into the manifest and backfilled the same way. Google Drive can't support this -- its `drive.file` OAuth scope only ever sees files the app itself created.
- **`frame_types.py`** — the `FRAME_TYPES` registry: every panel the integration knows how to drive (physical size label, resolution, `.bin` byte layout, and official-vs-community-clone origin). This is the extension point for supporting a new panel -- add a `FrameType` entry here declaring its layout explicitly rather than inferring it from resolution. A same-resolution/different-layout registration fails loudly at import time (`_validate_registry`) instead of silently corrupting another frame type's `.bin` cache.
- **`image_converter.py`** — converts any Pillow-readable image to Spectra 6 raw binary (4bpp, nibble-packed); byte layout (left/right half split vs. sequential) comes from `frame_types.py`, keyed by resolution
- **`fraimic-panel.js`** — vanilla JS custom panel; no frameworks; shadow DOM; talks to HA's REST/WS APIs with Bearer auth
- **`library_http.py`** — HTTP views registered with HA for the panel to call (image upload, crop save/clear, frame list, etc.)
- **`scenes.py`** — named (frame, image) assignment lists sendable all at once; local-only state (HA's `Store` helper), independent of the library's storage backend
- **`scenes_http.py`** — HTTP views for scene CRUD + send, mirroring `library_http.py`'s shape
- **`scene.py`** — exposes each saved scene as a `scene.*` entity (so Alexa/Google Assistant/Assist can activate it by name); lives on an auto-created, device-less "scenes hub" config entry rather than any frame's entry, since scenes are cross-frame state
- **`scene_packs.py`** / **`scene_packs_http.py`** — curated, installable image bundles (see "Scene packs" below)
- **`helpers.py`** — network utilities: `/api/info` probe, subnet scanner for IP self-healing, and `probe_device_size` (see below)
- **`config_flow.py`** — setup wizard. Physical panel size (`CONF_SIZE`, e.g. "13.3") is auto-detected during setup by scraping the "Device Type" field off `/info` -- a separate, human-facing HTML admin page, not `/api/info` -- since the JSON API doesn't expose size or resolution at all (confirmed against real hardware). The size dropdown only appears if that scrape fails. This is a best-effort parse of an undocumented page with no stability guarantee; if Fraimic ever changes that page's markup, setup just falls back to asking, it won't break.

## Scene packs

`scene_packs/` holds the content for one-click "install a pack" bundles surfaced in the panel: a manifest (`scene_packs/index.json`) plus resized source images, fetched at install time from GitHub raw content. Installing a pack runs its images through the normal `LibraryManager.async_upload()` pipeline (so it respects whatever storage backend the user already has configured) and auto-builds a scene by matching image orientation to each configured frame.

To add or refresh a pack, edit the `PACKS` list in `scripts/build_scene_pack.py` (a maintainer-only tool, not loaded by the integration) and run it:

```
python3 scripts/build_scene_pack.py
```

It searches Wikimedia Commons for each configured query, keeps only files whose license metadata explicitly says "public domain" *and* whose `Artist` metadata matches the expected artist (Commons full-text search can otherwise surface an unrelated painting for a loosely-worded query), downsizes them to a sane resolution, and rewrites `scene_packs/<pack_id>/` and `index.json`. Running it with no arguments rebuilds every pack in `PACKS` — review `git diff` before committing, since Commons occasionally reshuffles which scan ranks best for a given search. Pass one or more pack ids to rebuild only those and leave every other pack's existing `index.json` entry untouched, e.g. `python3 scripts/build_scene_pack.py christmas halloween`.

Every pack has a `category` field (`"art"` or `"seasonal"`), shown in the panel as a top-level browsing tile before the user drills into a category's packs. Set it on the `PACKS` entry — it flows straight through to `index.json`.

## Dev environment

You need a real Fraimic frame to test against — the frame's HTTP API is not documented publicly and there's no emulator. A Home Assistant instance on the same network as your frame is required.

1. Fork and clone the repo
2. Copy `custom_components/fraimic/` into your HA config's `custom_components/` directory (or symlink it)
3. Restart HA and add the integration

For iterating on Python changes, restart the integration from **Settings → Integrations → Fraimic → (three dots) → Reload** without a full HA restart.

For `fraimic-panel.js` changes, hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+R) — the panel JS is served directly and not cached aggressively.

## Testing image conversion

`image_converter.py` has no HA dependencies and can be tested standalone:

```python
from custom_components.fraimic.image_converter import convert_image_bytes
with open("photo.jpg", "rb") as f:
    bin_data = convert_image_bytes(f.read(), target_width=1200, target_height=1600)
with open("out.bin", "wb") as f:
    f.write(bin_data)
```

Send `out.bin` to a frame via its local API and verify it renders correctly. Color accuracy on Spectra 6 panels can vary — if something looks wrong on hardware, that's the ground truth.

## Testing the panel

`fraimic-panel.js` has a Playwright suite under `tests/panel/` that drives the real panel JS in an actual browser against a mocked backend — no HA instance or frame needed. This exists because the panel's real bugs (DOM/pointer-event handling, async fetch timing, `<script>`-scope shadowing) don't show up from reading the code. See `tests/panel/README.md` to run it and for what to add a test for when you fix a panel bug.

## Releasing (maintainers)

Releases are fully automatic. Every push to `main` (a direct commit or a merged PR) runs `bump-version.yaml`, which computes the next semver tag from the commit log, stamps it into `manifest.json`, pushes the tag, and publishes the GitHub release itself in the same job; HACS picks it up automatically. Don't hand-edit `manifest.json`'s `version` field — it's overwritten by the workflow. (`release.yaml` still exists as a fallback for a tag pushed manually with a real user token, but the automatic path doesn't depend on it — a tag pushed with the workflow's own token can't cascade-trigger another workflow.)

The default bump is `patch`. Put the exact-case token BUMPMINOR or BUMPMAJOR in a commit message (since the last tag) to bump that part instead. The matcher is a bash glob, not a literal-substring or regex match, so the token itself must avoid `#`, `[`, `]`, `*`, and `?` — square brackets in particular are a glob character class that can match almost any text, not the literal characters.

## Pull requests

- Keep PRs focused — one feature or fix per PR
- Test on real hardware before submitting; internally-consistent code that doesn't work on the frame is not useful
- `fraimic-panel.js` is intentionally vanilla JS with no build step — keep it that way
- If you're changing the bin conversion format, include before/after photos of the frame output

## Issues

Open an issue if you're seeing incorrect colors, display artifacts, or API errors. Include your frame model and firmware version (visible in the integration's device page).
