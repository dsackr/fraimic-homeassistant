# Key Product Flows

This is the catalog of Fraimic's Key Product Flows (KPFs) — the user-facing
capabilities the integration provides, kept current as the source of truth
for what "the product doing its job" means. Each entry says what breaks for
the end user if the flow silently fails, and where it's tested today.

**Maintenance rule (binding for all contributors, human or AI):** any change
that adds or alters user-facing behavior must land together with (a) a new
or amended KPF entry here — including an updated test-status line — and
(b) the tests that entry claims. See [AGENTS.md](../AGENTS.md) for the full
requirement. New KPFs are appended (numbers are stable identifiers referenced
from code and test docstrings — never renumber existing entries).

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

## 6. Voice/AI: "generate an image of X..." and "show [image name] on [frame]"
Custom Assist/LLM intents to generate an AI image or display an existing
library image on a named frame by voice.
- **Entry points**: `intent.py` (`FraimicGenerateAIImageIntent`,
  `FraimicShowImageIntent`, `_match_frame_device_id`).
- **If it silently breaks**: the voice command errors out, fails to find the
  image, or resolves to the wrong frame.
- **Test status**: **Backend-tested** — `tests/python/setup/test_intent.py`.

## 7. Image conversion pipeline (Spectra 6 .bin encoding + decoding)
Converts any Pillow-readable image into the frame's proprietary packed-
nibble binary format: auto-rotate, cover-crop, manual crop, canvas
rotation, dithering, and two byte layouts (split-half vs. sequential).
Also the reverse direction: unpacking a `.bin` back into an image, used to
build a preview thumbnail for sends that only ever see packed bytes (the
xOTD/skill text renderer — see KPF 28/29).
- **Entry points**: `image_converter.py` (`convert_image*`, `_process`,
  `_process_cropped`, `_pack_to_spectra6_bin` / `_pack_p_image_fast`,
  `default_cover_crop_box`, `unpack_spectra6_bin`, `preview_png_from_bin`).
- **If it silently breaks**: this is the "garbled/duplicated image on the
  physical frame" failure the module's own docstring calls out — no
  exception, just a wrong picture on real hardware. A broken unpacker is
  the softer cousin: wrong/blank card and panel thumbnails after xOTD sends.
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_image_converter.py`, including pack→unpack
  byte-exact round-trips against both byte layouts. Flagged as the riskiest
  silent-failure surface in the codebase in the initial gap analysis; also
  has a standalone byte-identity script (`scripts/verify_packing.py`) run
  manually against real photos when touching either packer.

## 8. Shared image library: upload, list, stream original, thumbnail, voice name
Users upload photos into one shared pool; images are listed/streamed for
the panel's grids with on-the-fly cached thumbnails, and can carry user-defined
voice names for Assist commands.
- **Entry points**: `library.py` (`LibraryManager.async_upload` /
  `list_images` / `get_original` / `get_thumbnail` / `async_set_image_voice_name`,
  `LocalLibraryBackend`), `library_http.py` (`FraimicLibraryImageVoiceNameView`).
- **If it silently breaks**: uploads silently fail per-file in a batch,
  thumbnails go stale/broken, or voice name edits fail to persist.
- **Test status**: Panel-tested (`dashboard.spec.js` covers grid rendering, album navigation, and voice name configuration/clearing; `lazy-thumbs.spec.js`).
  **Backend-tested** (local backend) —
  `tests/python/library/test_library_local_backend.py` (single/multi
  upload, undecodable-bytes tolerance, thumbnail cache generation/reuse,
  delete purges original + thumbnails, voice name updates).

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
- **Test status**: **Gap** — Dropbox/Google Drive backends and their OAuth
  flows are the remaining, highest-effort slice of Phase 5 (heavy
  request/response mocking for token exchange and refresh); not yet done.

## 10. Library discovery (adopt externally-added files)
Dropbox-only: photos dropped directly into the user's Dropbox get adopted
into the manifest and queued for `.bin` generation.
- **Entry points**: `library.py` (`DropboxLibraryBackend.async_discover_new_files`,
  `LibraryManager.async_discover`), `library_http.py`.
- **If it silently breaks**: dropped photos never appear in the panel, or
  get re-discovered forever if inbox removal fails.
- **Test status**: **Gap** — depends on the Dropbox backend above; same
  remaining slice of Phase 5.

## 11. Library `.bin` cache & background backfill
Every image gets a per-resolution `.bin` pre-generated in the background
across all configured frame resolutions/orientations; a send before
backfill finishes still works via on-demand conversion+cache.
- **Entry points**: `library.py` (`_schedule_backfill`,
  `_async_backfill_worker`, `async_get_bin_for_send`).
- **If it silently breaks**: sends are slow, or a send uses stale bytes
  after a crop change if cache invalidation is missed.
- **Test status**: **Backend-tested** —
  `tests/python/library/test_library_crop_albums_backfill.py` (backfill
  generates bins for configured frame resolutions, on-the-fly generation
  + caching when uncached, cache-hit skips reconversion, `pack_method`
  override bypasses the cache without polluting it).

## 12. Manual crop editing per image/resolution
User can save a manual crop rectangle for one image at one frame
resolution (or fallback per-orientation), invalidating cached renders.
Reachable from three places: the Library shelf's crop editor, the wall
image picker's "✂ Adjust Crop" (hands the staged/on-frame photo to the
same editor pre-targeted at that frame), and the Lovelace card's own
crop editor (KPF 29), whose "Save & Send" persists the crop then
immediately re-sends so the physical frame updates.
- **Entry points**: `library.py` (`async_set_crop`, `async_clear_crop`),
  `library_http.py` (`FraimicLibraryCropView`), `fraimic-panel.js`
  (`_openEditor`, `_cropFromWallPicker`), `fraimic-card.js` (`_openCrop`,
  `_cropSaveSend`).
- **If it silently breaks**: a saved crop doesn't apply on next send, or
  clearing a crop leaves stale cached renders for the same orientation.
- **Test status**: Panel-tested (`walls-crop-button.spec.js` — enable/
  disable rules and the wall-picker → editor handoff with the frame
  pre-targeted; `fraimic-card.spec.js` — the card's full crop flow
  including the save + re-send round trip against the mock server;
  `walls-image-picker.spec.js` covers the surrounding picker UI).
  **Backend-tested** — `tests/python/library/test_library_crop_albums_backfill.py`
  (exact-resolution save invalidates that bin, fallback-orientation save
  invalidates every matching resolution, clear reverts + invalidates,
  unknown image raises).

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
  **Backend-tested** — `tests/python/library/test_library_crop_albums_backfill.py`
  (create via tagging, rename/delete across multiple images, default-album
  protections, empty-name/empty-selection rejection).

## 14. Send library image to a frame
The panel's "Send to Canvas" — reuses/generates the cached `.bin` for that
frame's resolution and delivers or queues it.
- **Entry points**: `library_http.py` (`FraimicLibrarySendView`),
  `library.py` (`async_get_bin_for_send`), `coordinator.async_send_image_or_queue`.
- **If it silently breaks**: sends the wrong crop/orientation, or the
  packer A/B override leaks into the normal cache.
- **Test status**: Panel-tested (`packtest.spec.js`, `dashboard.spec.js`).
  The underlying `async_get_bin_for_send` (KPF 11) and
  `async_send_image_or_queue` (KPF 4) are both backend-tested; the HTTP
  view wrapper itself (`FraimicLibrarySendView`'s request/response
  marshaling) is still a **Gap**.

## 15. Direct upload-and-send (no library)
Card/API path: upload an image directly to a specific frame via multipart,
bypassing the library entirely (the Lovelace card's and wall picker's
upload buttons). Note: because these bytes never enter the library, the
sent photo can't be re-cropped afterwards (KPF 12's crop editors are
deliberately disabled for it).
- **Entry points**: `http_api.py` (`FraimicSendImageView`,
  `resolve_frame_by_entity`), `fraimic-card.js` (`_stageFile`/`_send`),
  `fraimic-panel.js` (`_sendFromWallPicker`).
- **If it silently breaks**: card sends silently fail, or the wrong frame
  receives the image.
- **Test status**: Panel-tested (`fraimic-card.spec.js` — upload staging
  and the multipart `send_image` POST with the right `entity_id`;
  `walls-send-and-offwall.spec.js` for the wall picker side). The Python
  view itself (`FraimicSendImageView`'s request/response marshaling) is
  still a **Gap** along with the rest of the `*_http.py` view layer (see
  the coverage summary below).

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
  covered). **Backend-tested** — `tests/python/managers/test_scenes.py`
  (CRUD, duplicate-name rejection, send_mappings partial-failure fan-out,
  schedule-disarm on delete).

## 17. Scene packs (curated art bundles, install/sync/uninstall)
One-click install of a public-domain image bundle that auto-builds a
matching scene, orientation-aware; sync repairs partial installs.
- **Entry points**: `scene_packs.py` (`ScenePackManager.async_install_pack` /
  `async_sync_pack` / `async_uninstall_pack`), `scene_packs_http.py`.
- **If it silently breaks**: an interrupted install leaves orphaned images
  untracked, blocking reinstall; uninstall can leave stray images if some
  deletes fail.
- **Test status**: Panel-tested indirectly (`addons-categories.spec.js`;
  `addons-catalog-refresh.spec.js` covers the catalog re-fetching on tab
  activation and panel revive rather than only once at initial load).
  **Backend-tested** — `tests/python/managers/test_scene_packs.py`
  (install success/partial-failure/all-fail, already-installed guard,
  uninstall scene+image cleanup and untag-vs-delete, sync recovery by
  filename, orientation-aware image-to-frame assignment).

## 18. Scene-pack "widgets" (agenda, quotes, scripture add-ons)
A pack type that downloads a Python renderer script + JSON config,
schedules it, and runs it as a subprocess to generate/send a rendered
image to one target frame. The agenda widget can pull from multiple
configured `calendar.*` entities at once (renamed from the older
one-entity-only "Home Assistant Calendar" field), merging events from
every selected calendar.
- **Entry points**: `scene_packs.py` (`_async_install_widget`,
  `_schedule_widget`, `async_run_widget`); the panel's generic
  `config_schema` engine (`fraimic-panel.js`) drives each widget's install
  form, including the `multiple` (checkbox-group, comma-joined entity ids)
  and `json` field types.
- **If it silently breaks**: a widget never runs (scheduler not armed), or
  a crashed subprocess silently does nothing forever.
- **Test status**: Panel-tested for config forms only
  (`addon-config-schema.spec.js`, `addon-schema-gaps.spec.js`,
  `agenda-calendar-source.spec.js`). Backend scheduling/execution: **Gap**
  — deliberately out of scope for Phase 4 (subprocess execution and the
  daily/hourly scheduler need heavier mocking than the rest of this phase;
  tracked as a follow-up in TESTING_STRATEGY.md rather than folded in here).

## 19. Walls: virtual multi-frame layout (panel-local state)
User arranges a subset of frames on a free-form canvas mirroring how
they're physically hung; custom walls and a default "All Frames" wall are
selected via visual picker tiles, and the default wall self-syncs with
configured frames. An "Align Wall to Grid" option allows users to snap all
placed frames on a wall to a clean structured layout. When aligning selected
frames, if they would overlap each other, they are automatically spaced out
along the other axis rather than producing a collision error.
- **Entry points**: `walls.py` (`WallManager.async_save_wall`,
  `async_ensure_default_wall`, `async_prune_entry`), `walls_http.py`,
  `fraimic-panel.js` (`_renderWallStrip`, `_openWall`, `_alignWallSelection`, `_alignWallToGrid`).
- **If it silently breaks**: removed/re-added frames haunt old layouts,
  the default wall stops tracking newly-added frames, or alignment features
  produce layout overlaps or throw unexpected error banners.
- **Test status**: Extensively panel-tested (`walls-drag.spec.js`,
  `walls-default-and-collision.spec.js`, `walls-multiselect.spec.js` — including
  alignment auto-spacing and Align Wall to Grid logic,
  `walls-flow.spec.js`, `walls-scenes-merge.spec.js`,
  `walls-send-and-offwall.spec.js`, `walls-image-picker.spec.js`,
  `walls-addon-album-lock.spec.js`) — but these exercise the frontend
  canvas/DOM logic against a mock server, not `WallManager` itself.
  **Backend-tested** — `tests/python/managers/test_walls.py` (custom wall
  CRUD, default-wall auto-sync, tombstone survival across resync, entry
  removal pruning, auto-layout collision math).

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
  delete, weekly validation). **Backend-tested** —
  `tests/python/managers/test_schedules.py` (trigger/action validation,
  missed-once fires late, recurring fire re-resolves the scene at fire
  time, target-deleted → target_missing + disabled, edit repairs a broken
  schedule, `next_fire_at` math including monthly day-of-month clamping).

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

## 26. Panel init-load resilience
On open (or after an HA restart/reconnect window), the panel retries each
of its initial data loads (frames, scenes, walls, etc.) with backoff
instead of taking a single failed fetch at face value, and never infers
"nothing configured yet" from a load that errored.
- **Entry points**: `fraimic-panel.js` (`_withInitRetry`, `_initLoadErrors`,
  `_initRetryDelays`/`_initRetriesActive`).
- **If it silently breaks**: a transient outage (HA restarting, a
  reconnect window) paints a believably-empty dashboard or wrongly opens
  the onboarding tour — Dale hit this in production before the fix (commit
  `a5b1a1b`) landed. The invariant: never make a zero-state claim from a
  load that errored; always distinguish ABSENT from UNKNOWN.
- **Test status**: Panel-tested (`tests/panel/init-retry.spec.js` — a
  transient outage recovers with no refresh needed, a persistent outage
  shows an "incomplete" note and never opens the tour, a broken
  onboarding-flag endpoint fails closed, a not-yet-ready websocket retries
  frame discovery, non-admins never see an admin-only error from an
  errored load). Backend: not applicable — this is frontend-only
  resilience against transient fetch failures.

## 27. Panel element lifecycle (listener/blob cleanup on disconnect)
The panel is a custom element HA recreates per navigation, not reused —
every `window`/`document` listener and every blob URL it creates (crop
editor previews, thumbnails) must be torn down on disconnect, or they leak
across every visit to the Frames panel for the life of the browser tab.
- **Entry points**: `fraimic-panel.js` (`disconnectedCallback`, the
  `this._abort` AbortController every listener registration is tied to,
  blob URL tracking in `this._thumbUrls`).
- **If it silently breaks**: a slow memory/listener leak that only shows
  up after navigating to the panel repeatedly in one browser session —
  invisible in a quick manual check, which is exactly how it shipped once
  already (commit `71c1b17`, "Sever the panel's global listeners and blob
  URLs on disconnect").
- **Test status**: Panel-tested (`tests/panel/lifecycle.spec.js` — detach
  severs listeners and revokes blob URLs; reattach after detach revives
  correctly; a same-tick DOM move, as HA sometimes does internally, must
  NOT tear anything down). Backend: not applicable.

## 28. Skills / Daily Content (xOTD): reusable content generators
User creates named "skills" (word/quote/joke/scripture of the day, image
feeds like NASA APOD / Wikimedia POTD / Bing wallpaper, or
random-from-album) and sends one to any frame — ad hoc ("Send Now" in the
Daily Content tab, the Lovelace card's Daily picker), staged into a scene
via the wall picker, or on a schedule. Text modes render through the
pinned remote `xotd_renderer.py` subprocess at the target frame's
resolution; image modes resolve to a library image_id (feeds upload the
fetched photo into the library first). Text renders also produce a
preview PNG (via KPF 7's unpacker) so the frame's last-image thumbnail
survives the send.
- **Entry points**: `skills.py` (`SkillManager.async_save_skill` /
  `async_render_for_entry` / `_async_render_text` /
  `_async_fetch_image_feed` / `_async_pick_image_album`),
  `skills_http.py` (CRUD + `FraimicSkillSendView`), fan-out via
  `scenes.py` (`async_send_mappings`).
- **If it silently breaks**: daily content stops arriving (schedules
  no-op), a skill renders blank/stale content, fan-out to several frames
  shows different content per frame, or — the regression fixed in July
  2026 — a text-skill send wipes the frame's last-image state so the
  card/panel thumbnail goes blank while the frame shows content.
- **Test status**: **Backend-tested** —
  `tests/python/managers/test_skills.py` (CRUD, per-mode render dispatch,
  feed fetch/upload, subprocess lifecycle + cleanup, preview-PNG
  generation with graceful degradation) and
  `tests/python/managers/test_scenes.py` (bin renders thread their
  preview through to the coordinator as the send thumbnail).
  Panel-tested — `skills.spec.js` (Daily Content tab),
  `walls-skill-picker.spec.js` (staging into scenes),
  `fraimic-card.spec.js` (card Daily picker send).

## 29. Lovelace card: per-frame dashboard management + last-image preview
The `fraimic-card` custom card: configured by picking a frame from a list
(entry_id; legacy battery-entity configs auto-resolve), it shows the
frame's latest displayed image — library sends via `last_image_id`,
upload/xOTD renders via the coordinator's persisted `last_thumbnail` —
and manages the frame from the dashboard: upload, library picker with
album filter, daily-skill send, orientation toggle, and crop adjustment
(KPF 12). The last-image preview state itself (mutually-exclusive
`last_image_id`/`last_thumbnail`, persisted per frame, exposed through
`/api/fraimic/frames` and `/api/fraimic/frame/{entry_id}/thumbnail`) is
part of this flow: every send path must leave it describing what the
frame actually shows.
- **Entry points**: `fraimic-card.js` (card + `fraimic-card-editor`),
  `coordinator.py` (`async_set_last_image`, `last_image_id` /
  `last_thumbnail` persistence), `library_http.py` (`FraimicFramesView`
  incl. `battery_entity_id`/`orientation_entity_id`/`online`,
  `FraimicFrameThumbnailView`), `http_api.py` (`FraimicFrameStatusView`).
- **If it silently breaks**: the card shows a stale or blank image while
  the frame shows something else (exactly what text-skill sends did
  before July 2026 — see KPF 28), the card picker falls back to raw YAML,
  or sends/orientation changes target the wrong frame.
- **Test status**: Panel-tested — `fraimic-card.spec.js` against the mock
  server + `card-harness.html` (editor frame list and entry_id config
  write, legacy entity resolution, both thumbnail sources incl. ETag'd
  render previews, upload/library/skill send round trips, orientation
  service call, crop flow). Coordinator preview persistence is
  backend-tested via `test_scenes.py`/`test_skills.py` (KPF 28); the
  frames/thumbnail HTTP views' own marshaling is still a **Gap** with the
  rest of the `*_http.py` layer.

---

## Coverage summary

| Phase | Scope | Status |
|---|---|---|
| 0 | Backend pytest infrastructure | Done |
| 1 | Image conversion, render spec, frame-type registry (KPFs 7, 22, 23) | Done |
| 2 | Coordinator: polling, IP healing, queue-on-sleep, concurrency (KPFs 3, 4) | Done |
| 3 | Config flow, setup lifecycle, services, intent, entities, onboarding backend (KPFs 1, 2, 5, 6, 21, 24, 25) | Done |
| 4 | Scenes, scene packs, walls, schedules, skills managers (KPFs 16, 17, 19, 20, 28) | Done (KPF 18's widget scheduling/subprocess execution still a gap) |
| 5 | Library: local backend, crop, albums, backfill (KPFs 8, 11, 12, 13) | Done |
| 5b | Library: Dropbox/Google Drive cloud backends + OAuth, discovery (KPFs 9, 10), and the `*_http.py` view layer (KPFs 14, 15, 29's views + the rest) | Planned |
| — | Panel init-load resilience, panel element lifecycle, Lovelace card (KPFs 26, 27, 29) | Done — frontend side; KPF 29's HTTP views fold into 5b |

Phase 5b (plus KPF 18's widget scheduling) is scoped here but not yet
implemented — see [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) for the
checkpoint tracker.
