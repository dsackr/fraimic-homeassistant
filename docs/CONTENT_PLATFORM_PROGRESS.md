# Content platform — implementation progress / handoff

**Read this first if resuming work.** Full plan: [CONTENT_PLATFORM_ROADMAP.md](CONTENT_PLATFORM_ROADMAP.md).

| Field | Value |
|---|---|
| **Last updated** | 2026-07-19 |
| **Active phase** | **Complete through Phase 7** |
| **Branch** | `main` |
| **Repos** | this repo + `../frame-addons` |

## Status board

| Phase | Status | Notes |
|:---:|---|---|
| 0–6 | **done** | Gallery/Live, agenda skill, widget purge |
| **7 Marketplace foundations** | **done** | versioned catalog, checksums, search/featured, community template |

## Phase 7 summary

### frame-addons
- `scripts/stamp_catalog.py` — stamps `schema_version`, pack `version` /
  `min_integration` / `featured`, per-image `sha256`
- `docs/CATALOG_SCHEMA.md` — catalog contract
- `.github/PULL_REQUEST_TEMPLATE/art_pack.md` — community PR checklist
- `scene_packs/index.json` restamped (28 packs, 253 checksums)

### Integration
- Filters packs by `min_integration` vs `manifest.json` version
- Verifies `sha256` on image download when present
- `GET /api/digital_frames/scene_packs` returns `catalog` metadata
- Gallery UI: search box, Featured strip, version on pack cards

### Explicit non-goals (still out of scope)
- Community remote-exec Python
- Multi-publisher signed marketplaces beyond checksum integrity

## Follow-ups (optional polish, not blocking)
- Wire `stamp_catalog.py` into `build_scene_pack.py` so rebuilds auto-stamp
- Panel Playwright coverage for Featured + search
- Rename `ScenePackManager` → `ArtPackManager`
