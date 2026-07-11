# Key Product Flows

This is the catalog of Fraimic's Key Product Flows (KPFs) — the user-facing
capabilities the integration provides, kept current as the source of truth
for what "the product doing its job" means. Each entry says what breaks for
the end user if the flow silently fails, and where it's tested today.

See [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) for the testing standard
this catalog feeds into, and [CONTRIBUTING.md](../CONTRIBUTING.md) for how
the codebase is laid out.

Test status legend:
- **Backend-tested** — `tests/python/` exercises the Python logic directly.
- **Panel-tested** — `tests/panel/` exercises the frontend against a mocked
  backend (see `tests/panel/README.md`); the Python side may still be
  untested.
- **Gap** — no automated coverage yet, backend or frontend.

---

## 1. Frame discovery & add-frame wizard
User points HA at their local network (or an IP) and the config flow finds
or adds a Fraimic frame, auto-detecting its size/resolution.
- **Entry points**: `config_flow.py` (`FraimicConfigFlow.async_step_user` /
  `pick_device` / `manual` / `name_device` / `dhcp` / `integration_discovery`),
  `helpers.py` (`probe_frame`, `probe_device_size`, `scan_subnet`,
  `detect_frame_type_from_info`), `discovery.py`.
- **If it silently breaks**: users can't add frames at all, or duplicate
  entries get created for the same physical frame.
- **Test status**: Panel-tested (`flow-renderer.spec.js`,
  `frame-manage.spec.js`). **Backend-tested** —
  `tests/python/config_flow/test_config_flow_user_scan.py` (user/manual/
  pick_device/DHCP steps, size auto-detect, dedup).

## 2. Options flow (scan interval, size, orientation edge, 180° flip)
User edits a frame's scan interval, physical size, hanging edge, and
180°-rotation flags via HA's Configure dialog.
- **Entry points**: `config_flow.py` (`FraimicOptionsFlow.async_step_init`).
- **If it silently breaks**: settings don't stick, or the orientation lock
  resets when saving an unrelated field.
- **Test status**: Panel-tested (`flow-renderer.spec.js`). **Backend-tested** —
  `tests/python/config_flow/test_config_flow_options.py`.

## 3. Coordinator polling & IP self-healing
Each frame is polled periodically for battery/wifi/firmware/dimensions; if
it goes silent for 3 polls, a subnet rescan finds its new IP (a DHCP-moved
frame).
- **Entry points**: `coordinator.py` (`FraimicCoordinator._async_update_data`,
  `_async_try_find_new_host`, `_maybe_persist_fingerprint`).
- **If it silently breaks**: sensors go "unavailable" forever after a router
  reassigns the frame's IP; the user thinks the frame is dead.
- **Test status**: **Backend-tested** —
  `tests/python/coordinator/test_coordinator_polling.py`,
  `test_coordinator_concurrency.py`.

## 4. Send image now (queue-if-asleep) — the core send primitive
Every "send to frame" path (service, raw upload, library send, scene send,
schedule fire) funnels through one send-or-queue mechanism so a sleeping
frame gets the image on wake instead of losing it or double-sending.
- **Entry points**: `coordinator.py` (`async_send_image_or_queue`,
  `_async_flush_pending_send`, `_set_pending`, `_clear_pending_if_current`).
- **If it silently breaks**: images sent to a sleeping frame vanish, or a
  wake causes a duplicate redraw.
- **Test status**: **Backend-tested** —
  `tests/python/coordinator/test_coordinator_queue_on_sleep.py`. The single
  highest-value target in this catalog per the initial gap analysis.

## 5. HA services (send_image, send_scene, restart, sleep, refresh, generate_ai_image)
Lets automations/scripts drive a frame: send an arbitrary media item, send
a named scene, or issue restart/sleep/refresh commands.
- **Entry points**: `__init__.py` (`_register_services`, `_handle_send_image`,
  `_handle_send_scene`, `_handle_generate_ai_image`, `_resolve_media_path`).
- **If it silently breaks**: automations calling `fraimic.send_image` /
  `send_scene` fail or send the wrong image; a path-traversal bug in media
  resolution could leak files.
- **Test status**: **Backend-tested** — `tests/python/setup/test_services.py`
  (command services, send_image media resolution + path-escape rejection,
  send_scene aggregation semantics).

## 6. Voice/AI: "generate an image of X and send to [frame]"
A single Assist/LLM intent that generates an AI image and sends it to a
named frame by voice.
- **Entry points**: `intent.py` (`FraimicGenerateAIImageIntent`,
  `_match_frame_device_id`).
- **If it silently breaks**: the voice command errors out or resolves to
  the wrong frame.
- **Test status**: **Backend-tested** — `tests/python/setup/test_intent.py`.

## 7. Image conversion pipeline (Spectra 6 .bin encoding)
Converts any Pillow-readable image into the frame's proprietary packed-
nibble binary format: auto-rotate, cover-crop, manual crop, canvas
rotation, dithering, and two byte layouts (split-half vs. sequential).
- **Entry points**: `image_converter.py` (`convert_image*`, `_process`,
  `_process_cropped`, `_pack_to_spectra6_bin` / `_pack_p_image_fast`,
  `default_cover_crop_box`).
- **If it silently breaks**: this is the "garbled/duplicated image on the
  physical frame" failure the module's own docstring calls out — no
  exception, just a wrong picture on real hardware.
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_image_converter.py`. Flagged as the riskiest
  silent-failure surface in the codebase in the initial gap analysis; also
  has a standalone byte-identity script (`scripts/verify_packing.py`) run
  manually against real photos when touching either packer.

## 8. Shared image library: upload, list, stream original, thumbnail
Users upload photos into one shared pool; images are listed/streamed for
the panel's grids with on-the-fly cached thumbnails.
- **Entry points**: `library.py` (`LibraryManager.async_upload` /
  `list_images` / `get_original` / `get_thumbnail`, `LocalLibraryBackend`),
  `library_http.py`.
- **If it silently breaks**: uploads silently fail per-file in a batch, or
  thumbnails go stale/broken.
- **Test status**: Panel-tested (`dashboard.spec.js`, `lazy-thumbs.spec.js`).
  Backend: **Gap** — planned for Phase 5.

## 9. Library storage backend switching (Local / Dropbox / Google Drive)
User can point the whole library at Dropbox or Google Drive instead of
local disk, with validation before switching and fallback to local on
failure.
- **Entry points**: `library.py` (`LibraryManager.async_set_backend` /
  `async_load`, `DropboxLibraryBackend`, `GoogleDriveLibraryBackend`),
  `library_http.py` (OAuth start/callback/redirect-uri views).
- **If it silently breaks**: switching backends fails and silently reverts
  to local without the user noticing, stranding photos on the wrong
  storage.
- **Test status**: **Gap** — planned for Phase 5.

## 10. Library discovery (adopt externally-added files)
Dropbox-only: photos dropped directly into the user's Dropbox get adopted
into the manifest and queued for `.bin` generation.
- **Entry points**: `library.py` (`DropboxLibraryBackend.async_discover_new_files`,
  `LibraryManager.async_discover`), `library_http.py`.
- **If it silently breaks**: dropped photos never appear in the panel, or
  get re-discovered forever if inbox removal fails.
- **Test status**: **Gap** — planned for Phase 5.

## 11. Library `.bin` cache & background backfill
Every image gets a per-resolution `.bin` pre-generated in the background
across all configured frame resolutions/orientations; a send before
backfill finishes still works via on-demand conversion+cache.
- **Entry points**: `library.py` (`_schedule_backfill`,
  `_async_backfill_worker`, `async_get_bin_for_send`).
- **If it silently breaks**: sends are slow, or a send uses stale bytes
  after a crop change if cache invalidation is missed.
- **Test status**: **Gap** — planned for Phase 5.

## 12. Manual crop editing per image/resolution
User can save a manual crop rectangle for one image at one frame
resolution (or fallback per-orientation), invalidating cached renders.
- **Entry points**: `library.py` (`async_set_crop`, `async_clear_crop`),
  `library_http.py` (`FraimicLibraryCropView`).
- **If it silently breaks**: a saved crop doesn't apply on next send, or
  clearing a crop leaves stale cached renders for the same orientation.
- **Test status**: Panel-tested indirectly (`walls-image-picker.spec.js`
  covers the picker UI, not the crop-save round trip itself). Backend:
  **Gap** — planned for Phase 5.

## 13. Album management (tag, rename, delete, batch-add)
Photos can be tagged into any number of albums; albums are emergent from
tags, with rename/delete affecting every tagged image in one bulk write.
- **Entry points**: `library.py` (`async_list_albums`,
  `async_set_image_albums`, `async_rename_album`, `async_delete_album`),
  `library_http.py`.
- **If it silently breaks**: rename/delete misses images, or the default
  "Images" album gets renamed/deleted, breaking the "always at least one
  album" invariant.
- **Test status**: Panel-tested indirectly (`walls-addon-album-lock.spec.js`).
  Backend: **Gap** — planned for Phase 5.

## 14. Send library image to a frame
The panel's "Send to Canvas" — reuses/generates the cached `.bin` for that
frame's resolution and delivers or queues it.
- **Entry points**: `library_http.py` (`FraimicLibrarySendView`),
  `library.py` (`async_get_bin_for_send`), `coordinator.async_send_image_or_queue`.
- **If it silently breaks**: sends the wrong crop/orientation, or the
  packer A/B override leaks into the normal cache.
- **Test status**: Panel-tested (`packtest.spec.js`, `dashboard.spec.js`).
  Backend: **Gap** — planned for Phase 5.

## 15. Direct upload-and-send (no library)
Card/API path: upload an image directly to a specific frame via multipart,
bypassing the library entirely (the Lovelace card's path).
- **Entry points**: `http_api.py` (`FraimicSendImageView`,
  `resolve_frame_by_entity`).
- **If it silently breaks**: card sends silently fail, or the wrong frame
  receives the image.
- **Test status**: **Gap** — planned for Phase 5 (outside the panel test
  suite's stated scope).

## 16. Scenes: named multi-frame image assignments (CRUD + send)
User builds a named "scene" (frame→image mapping) and sends every frame's
assigned image at once; exposed as `scene.*` entities for voice control.
- **Entry points**: `scenes.py` (`SceneManager.async_save_scene` /
  `async_delete_scene` / `async_send_scene` / `async_send_mappings`),
  `scene.py`, `scenes_http.py`.
- **If it silently breaks**: partial-failure semantics could be wrong (one
  dead frame blocking the whole scene, or a fully-failed scene reporting
  success).
- **Test status**: Panel-tested (`walls-scenes-merge.spec.js`,
  `walls-flow.spec.js` — scene CRUD outside the Walls UI isn't directly
  covered). Backend: **Gap** — planned for Phase 4.

## 17. Scene packs (curated art bundles, install/sync/uninstall)
One-click install of a public-domain image bundle that auto-builds a
matching scene, orientation-aware; sync repairs partial installs.
- **Entry points**: `scene_packs.py` (`ScenePackManager.async_install_pack` /
  `async_sync_pack` / `async_uninstall_pack`), `scene_packs_http.py`.
- **If it silently breaks**: an interrupted install leaves orphaned images
  untracked, blocking reinstall; uninstall can leave stray images if some
  deletes fail.
- **Test status**: Panel-tested indirectly (`addons-categories.spec.js`).
  Backend: **Gap** — planned for Phase 4.

## 18. Scene-pack "widgets" (agenda, quotes, scripture add-ons)
A pack type that downloads a Python renderer script + JSON config,
schedules it, and runs it as a subprocess to generate/send a rendered
image to one target frame.
- **Entry points**: `scene_packs.py` (`_async_install_widget`,
  `_schedule_widget`, `async_run_widget`).
- **If it silently breaks**: a widget never runs (scheduler not armed), or
  a crashed subprocess silently does nothing forever.
- **Test status**: Panel-tested for config forms only
  (`addon-config-schema.spec.js`, `addon-schema-gaps.spec.js`,
  `agenda-calendar-source.spec.js`). Backend scheduling/execution: **Gap**
  — planned for Phase 4.

## 19. Walls: virtual multi-frame layout (panel-local state)
User arranges a subset of frames on a free-form canvas mirroring how
they're physically hung; a default "All Frames" wall self-syncs with
configured frames.
- **Entry points**: `walls.py` (`WallManager.async_save_wall`,
  `async_ensure_default_wall`, `async_prune_entry`), `walls_http.py`.
- **If it silently breaks**: removed/re-added frames haunt old layouts, or
  the default wall stops tracking newly-added frames.
- **Test status**: Extensively panel-tested (`walls-drag.spec.js`,
  `walls-default-and-collision.spec.js`, `walls-multiselect.spec.js`,
  `walls-flow.spec.js`, `walls-scenes-merge.spec.js`,
  `walls-send-and-offwall.spec.js`, `walls-image-picker.spec.js`,
  `walls-addon-album-lock.spec.js`) — but these exercise the frontend
  canvas/DOM logic against a mock server, not `WallManager` itself.
  Backend: **Gap** — planned for Phase 4.

## 20. Schedules: send a scene or image at a future/recurring time
User schedules a one-shot or daily/weekly/monthly recurring send; missed
one-shots fire late on restart; a deleted scene/image target degrades a
schedule to "broken" instead of erroring at fire time.
- **Entry points**: `schedules.py` (`ScheduleManager.async_create_schedule`,
  `_arm`, `_async_fire`, `_async_fire_missed`,
  `async_handle_scene_deleted`, `next_fire_at`), `schedules_http.py`.
- **If it silently breaks**: missed schedules never fire after an outage,
  or a schedule keeps trying to fire against a deleted target forever.
- **Test status**: Panel-tested (`schedules.spec.js` — create/edit/toggle/
  delete, weekly validation). Backend recurrence math (`next_fire_at`,
  monthly clamping, missed-fire-on-restart): **Gap** — planned for Phase 4.

## 21. HA entities: sensors + Orientation select
Read-only device telemetry (battery/wifi/charging/firmware/IP/queued) plus
one per-frame Orientation control that persists into config entry options
and feeds the render pipeline.
- **Entry points**: `sensor.py` (all `Fraimic*Sensor` classes), `select.py`
  (`FraimicOrientationSelect`).
- **If it silently breaks**: wrong/missing sensor values for a firmware
  shape not yet seen, or selecting an orientation doesn't actually change
  rendering.
- **Test status**: **Backend-tested** — `tests/python/setup/test_entities.py`.

## 22. Render spec resolution (orientation lock + rotation + hanging edge)
Central "how should this image be composed for this frame" resolution —
combines native dimensions, orientation lock, 180° flips, and hang-edge
into one `RenderSpec` every send path consults.
- **Entry points**: `helpers.py` (`render_spec_for_entry`,
  `RenderSpec.variant`).
- **If it silently breaks**: this is the single riskiest piece of logic in
  the whole integration — a wrong rotation means every image sent from
  every path lands sideways or upside-down on the physical frame, and it's
  invisible until someone looks at hardware.
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_helpers_render_spec.py`.

## 23. Frame-type registry & byte-layout dispatch
Declares every supported physical panel (resolution, byte layout,
official/clone origin) and validates no two types sharing a resolution
disagree on layout.
- **Entry points**: `frame_types.py` (`FRAME_TYPES`, `_validate_registry`,
  `byte_layout_for_resolution`).
- **If it silently breaks**: garbled image on an unregistered/misregistered
  panel size (same failure mode as image conversion, one layer up).
- **Test status**: **Backend-tested** — `tests/python/unit/test_frame_types.py`.

## 24. First-run onboarding wizard + server-side completion flag
Six-step first-run tour; "skip"/"complete" retires the wizard for every
admin, forever, via a server-side flag (not localStorage).
- **Entry points**: `http_api.py` (`FraimicOnboardingView`).
- **If it silently breaks**: the wizard reappears every session for every
  admin, or one admin's skip doesn't stick for others.
- **Test status**: Panel-tested (`onboarding.spec.js`, full six-step tour
  and skip variants). **Backend-tested** — `tests/python/setup/test_onboarding.py`
  (admin-gating + Store persistence).

## 25. Domain-level setup wiring
`async_setup` / `async_setup_entry` / `async_unload_entry` /
`async_remove_entry` — bootstraps everything above: registers HTTP views,
the sidebar panel, the Lovelace card, auto-creates the device-less
scenes-hub entry, and tears down cleanly when the last frame is removed.
- **Entry points**: `__init__.py`.
- **If it silently breaks**: this is glue — a failure here means the whole
  integration fails to load, or (subtler) removing the last frame leaves
  scene-pack/schedule timers running forever, or doesn't prune wall
  layouts.
- **Test status**: **Backend-tested** — `tests/python/setup/test_init_setup_entry.py`
  (scenes-hub auto-creation, service lifecycle, wall-placement pruning on
  removal, reload on option change).

---

## Coverage summary

| Phase | Scope | Status |
|---|---|---|
| 0 | Backend pytest infrastructure | Done |
| 1 | Image conversion, render spec, frame-type registry (KPFs 7, 22, 23) | Done |
| 2 | Coordinator: polling, IP healing, queue-on-sleep, concurrency (KPFs 3, 4) | Done |
| 3 | Config flow, setup lifecycle, services, intent, entities, onboarding backend (KPFs 1, 2, 5, 6, 21, 24, 25) | Done |
| 4 | Scenes, scene packs + widgets, walls, schedules managers (KPFs 16–20) | Planned |
| 5 | Library backends, backfill, crop, albums, HTTP views (KPFs 8–15) | Planned |

Phases 4-5 are scoped here but not yet implemented — see
[TESTING_STRATEGY.md](../TESTING_STRATEGY.md) for the checkpoint tracker.
