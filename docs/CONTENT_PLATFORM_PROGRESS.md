# Content platform — implementation progress / handoff

**Read this first if resuming work.** Full plan: [CONTENT_PLATFORM_ROADMAP.md](CONTENT_PLATFORM_ROADMAP.md).

| Field | Value |
|---|---|
| **Last updated** | 2026-07-19 |
| **Active phase** | **Phase 6 optional** (catalog split polish) — Phases 0–5 done |
| **Branch** | `main` (commit after this session) |
| **Repos** | this repo + `../frame-addons` |

## Status board

| Phase | Status | Notes |
|:---:|---|---|
| 0 Contract | **done** | Roadmap + handoff |
| 1 Surface rename | **done** | Gallery / Live |
| 2 Gallery install UX | **done** | library-only |
| 3 Live quick-setup | **done** | Schedule daily |
| 4 Agenda as Live | **done** | skill + pin + migration |
| 5 Retire widgets | **done** | install rejected; catalog clean |
| 6 Catalog split | optional | art-only already (no widgets in index) |
| 7 Marketplace | not started | Later |

## What shipped in Phases 4–5

### frame-addons
- `agenda_renderer.py`: `--render-only`, `--config`, outputs `agenda.bin` + `agenda_preview.png`
- Pinned commit for skills: `779df8acbec36385c277df346e48ecf025ad5fb3`
- Catalog: removed `xotd` and `daily_agenda` widgets (art packs only)

### Integration
- `content_mode=agenda`, built-in skill `daily_agenda`
- `AGENDA_RENDERER_*` pins in `const.py`
- Prefetch HA calendar → `ha_events.json` in render temp dir
- `_async_migrate_agenda_widget` on setup
- Widget install/sync rejected with Live-tab message
- Panel: agenda mode tile + config fields; Gallery copy no longer promises Tools widgets

### Tests
- `tests/python/setup/test_agenda_migration.py`
- skills built-in seeding includes Daily Agenda

## Phase 6 (optional polish)
- Rename `ScenePackManager` → `ArtPackManager` (behavior-preserving)
- Drop dead `_async_install_widget` / `async_run_widget` code bodies entirely if still present
- Panel: remove widget modal if unused

## Phase 7
- Versioned art catalog / community images only — see roadmap
