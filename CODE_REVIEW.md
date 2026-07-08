# Fraimic HA Integration — Code Review

**Reviewed:** v0.12.25
**Date:** 2026-07-05
**Files:** `__init__.py`, `coordinator.py`, `config_flow.py`, `const.py`, `frame_types.py`, `helpers.py`, `image_converter.py`, `sensor.py`, `select.py`, `scene.py`, `http_api.py`, `library.py`, `library_http.py`, `scene_packs.py`, `scene_packs_http.py`, `scenes.py`, `scenes_http.py`, `walls.py`, `walls_http.py`, `fraimic-card.js`, `fraimic-panel.js`

---

## Summary

The integration has grown roughly 8x since the last audit (v0.1.6 → v0.12.25), adding a shared photo library, scene packs, scenes, and multi-frame "walls." The core patterns from the last review — executor offloading for blocking work, `async_get_clientsession` for frame communication, manifest locking, HTML escaping in the panel — are followed consistently in the new code, and both Critical items from the v0.1.6 review (`_safe_media_join` path-traversal guard, the cover-vs-letterbox resize) are confirmed fixed and correctly documented. However, the same *class* of path-traversal bug the last review fixed has been reintroduced in the newer Library code, a scene-pack feature has a guaranteed crash, and two long-standing High findings from the old review are still open, unfixed, 122 commits later.

---

## Critical

### 1. Uninstalling any scene pack always crashes with `NameError`, after already deleting its scene (`scene_packs.py:367-378`)

```python
async def async_uninstall_pack(self, pack_id: str) -> None:
    installed = self._installed.get(pack_id)
    ...
    if installed.get("scene_id"):
        await self._scenes.async_delete_scene(installed["scene_id"])   # scene is gone

    library_images = await self._library.async_list_images()
    images_by_id = {img["image_id"]: img for img in library_images}
    album_to_remove = installed.get("album", pack["name"])              # <-- `pack` is never defined
```

`pack` doesn't exist anywhere in this method's scope — it raises `NameError` unconditionally, on every call. Python evaluates `dict.get`'s default argument eagerly, so this crashes regardless of whether `"album"` is present in `installed`. Worse, the pack's scene is already deleted two lines earlier, so every uninstall attempt leaves the pack half-torn-down: scene gone, pack still marked installed, images never cleaned up, and every retry fails identically.

**Fix**: `album_to_remove = installed.get("album", installed.get("pack_name", pack_id))` (or whatever field actually holds the pack's display name — audit `installed`'s schema, since `pack` was clearly meant to reference the pack's own record, not a bare-word typo).

### 2. Unsanitized `image_id` path traversal in the Library's `.bin` cache (`library.py:296`, `:387-396`)

```python
def _bin_path(self, image_id: str, width: int, height: int, variant: str = "") -> str:
    return os.path.join(self._root, "bin", f"{width}x{height}{variant}", f"{image_id}.bin")
```

Unlike `_original_path_for` (`library.py:299-302`), which correctly runs the filename through `_safe_filename()`, `_bin_path` interpolates `image_id` into the path with no sanitization at all — the exact class of bug `_safe_media_join` was written to fix elsewhere in this codebase.

- **Read side**: `async_get_bin_for_send` (`library.py:1435+`) is called from the send endpoint (`library_http.py:263-294`), which pulls `image_id` straight out of the JSON request body (`body.get("image_id")`) with only an empty-string check — no format validation, no manifest membership check before the path is built. A crafted `image_id` like `../../../../some/other/dir/x` reads whatever `<that path>.bin` exists outside the library root and sends its raw bytes to the frame.
- **Delete side**: `_delete_image_sync` (`library.py:387-396`) builds `candidate = os.path.join(bin_root, res_dir, f"{image_id}.bin")` and calls `os.remove(candidate)` — reachable from `DELETE /api/fraimic/library/image/{image_id}` (`library_http.py:198-204`) with no format check either.

Both are bounded to filenames ending in `.bin`, which limits — but does not eliminate — the blast radius (arbitrary `.bin` file read/delete anywhere the HA process can reach, not full arbitrary-file read).

**Fix**: add a `_safe_image_id` check (reject anything containing `/`, `\`, or `..`, or better, validate it's the expected hex-UUID shape from `uuid.uuid4().hex[:12]`) and apply it at the top of `_bin_path` and everywhere `image_id` is interpolated into a path.

### 3. `send_image` service accepts an arbitrary absolute filesystem path with no sandboxing (`__init__.py:395-399`)

```python
if media_content_id.startswith("/media/"):
    local_dir = hass.config.media_dirs.get("local", hass.config.path("media"))
    return _safe_media_join(local_dir, media_content_id[len("/media/"):])

return media_content_id   # <-- falls through unchanged for anything else
```

`_resolve_media_path` only sandboxes the `media-source://…` and `/media/…` shapes. Any other string — e.g. a literal `/config/www/private/photo.jpg` or any other path readable by the HA process — falls through to `return media_content_id` verbatim. `_handle_send_image` (`__init__.py:420-463`) then does `os.path.isfile(abs_path)` and feeds it straight to Pillow via `convert_image_with_preview`. Any automation, script, or Developer Tools → Services call can pass an arbitrary path here; the `media` selector in `services.yaml` is a UI hint, not server-side validation. This is strictly broader than the traversal bug the old review fixed — that one at least tried to stay under a media root; this branch has no root at all.

**Fix**: reject anything that isn't `media-source://` or `/media/`-prefixed instead of returning it unchanged:
```python
raise HomeAssistantError(
    f"Unsupported media_content_id (must be a media-source:// URI or /media/ path): {media_content_id}"
)
```

---

## High

### 4. DHCP self-healing and dimension-sync writes trigger a full config-entry reload, defeating their own purpose (`__init__.py:283, 294, 324-326`; `coordinator.py:168, 208, 276, 294-307`)

Two listeners are registered on the same entry: `coordinator.async_config_entry_updated` (whose docstring says it exists specifically to *"pick up a new host without restarting the integration"*) and `_async_update_listener`, which unconditionally calls `hass.config_entries.async_reload(entry.entry_id)`. `hass.config_entries.async_update_entry()` fires **every** registered listener regardless of which field changed — so the three legitimate `entry.data`-only writes (DHCP IP change via `_async_try_find_new_host`, subnet-rescan self-heal, and dimension sync when a frame reports new width/height) all also trigger the full reload the coordinator's own listener was written to avoid. The coordinator even has a comment (lines 40-46) explaining they deliberately avoided `entry.options` for the preview store *"that would trigger a full entry reload on every single send"* — the same hazard was missed for `entry.data`.

**Fix**: only reload from `_async_update_listener` when option keys that actually require a reload changed, or drop the blanket listener and reload explicitly from the call sites that need it (e.g. `FraimicOptionsFlow`).

### 5. ~~Blocking `socket.connect()` still runs directly on the event loop in the config flow~~ — RESOLVED

**Resolved** as part of the dashboard-consolidation work (periodic discovery made this load-bearing): the logic now lives once in `helpers.get_local_ip()`, and every caller (`config_flow.async_step_user` both branches, `coordinator._async_try_find_new_host`) invokes it via `hass.async_add_executor_job`. The coordinator's inline duplicate `_detect_local_ip` was deleted.

### 6. Service handlers still don't catch `aiohttp.ClientError` from the coordinator (`coordinator.py:313-348`; `__init__.py:405-418, 450`) — unfixed since the v0.1.6 review

`async_send_command`/`async_send_image` log and re-raise the raw `aiohttp.ClientError`. None of `_handle_restart`/`_handle_sleep`/`_handle_refresh`/`_handle_send_image` catch it, so a network blip or offline frame surfaces as an unhandled traceback in the HA log instead of a clean `HomeAssistantError`.

**Fix**: wrap and re-raise as `HomeAssistantError` inside the two coordinator methods, as recommended in the original review.

### 7. Thumbnail and crop-editor blob URLs leak when the panel is disposed mid-fetch (`fraimic-panel.js:2641-2669`, `:3219-3235`, `_dispose` at `:1169-1189`)

`_dispose()` (run on every panel navigation) revokes everything in `this._thumbUrls` and resets the fetch-tracking containers, but neither `_fetchThumb`'s nor `_openEditor`'s full-size-image `fetch()` is tied to `this._abort.signal`, and neither checks a disposed flag before calling `URL.createObjectURL`. A thumbnail or full-size image still loading when the user navigates away creates a fresh blob URL on an object `_dispose()` has already replaced — never revoked, since HA recreates the panel element per visit rather than reusing it. This is the same leak class `71c1b17` ("Sever the panel's global listeners and blob URLs on disconnect") was written to close, reintroduced in the async-continuation path it didn't cover. Not exercised by `tests/panel/lifecycle.spec.js`, which waits for the thumbnail to finish loading before detaching.

**Fix**: pass `{ signal: this._abort.signal }` to both `fetch()` calls, or check a disposed flag immediately before `URL.createObjectURL` and revoke-on-arrival if set.

### 8. Switching albums quickly renders the wrong photos under the wrong title (`fraimic-panel.js:2353-2357` `_openAlbum`)

```js
async _openAlbum(name) {
  this._currentAlbum = name;
  await this._loadLibrary(name);
  this._renderLibrary();
}
```
No staleness guard: clicking two album tiles in quick succession starts two concurrent calls, and `this._currentAlbum` (set synchronously, last-writer-wins) can end up naming a different album than `this._library` (set by whichever fetch resolves last) actually contains. The codebase already has the right pattern for this exact shape of bug — `_loadWallImagePickerImages` (`:4739-4779`) uses an incrementing token to discard superseded responses — but `_openAlbum` doesn't use it. Not covered by any Playwright spec.

**Fix**: apply the same token pattern used in the wall image picker.

### 9. Crop editor can silently save a corrupted, wrong-image crop (`fraimic-panel.js:3161-3238` `_openEditor`/`_closeEditor`)

`_closeEditor` nulls `_editorState` and revokes the blob URL but doesn't cancel or invalidate an in-flight `_openEditor` fetch, and `_openEditor` has no per-call staleness token. If image A's fetch is still pending when the editor is closed and reopened for image B (plausible on a slow connection with a large photo), A's fetch resolves after B is already showing, and its continuation writes A's blob URL, `naturalW`/`naturalH` onto the *current* (`stateB`) editor state via `this._editorState` — visibly swapping the picture back to A while `stateB.image.image_id` (the actual save target) is untouched. The result: a crop computed from image A's dimensions gets persisted against image B. No test exercises the crop editor at all.

**Fix**: capture a token or `image.image_id` at the top of `_openEditor` and no-op the post-fetch continuation if `this._editorState` no longer matches it.

---

## Medium

### 10. Cloud library backends silently treat failed remote deletes as success (`library.py:791, 1027`)

Dropbox/Google Drive delete calls don't check the response status, so a failed remote delete is treated as a successful local removal, orphaning the file in the user's cloud storage with no error surfaced.

### 11. `async_delete_bin` doesn't update the manifest's `resolutions` list (`library.py:464`)

A background backfill sweep can skip regenerating a resolution whose `.bin` was actually deleted, since the manifest still claims it exists. Currently masked by an on-demand fallback at send time, so not user-visible yet, but the manifest and disk state disagree.

### 12. Unguarded `float()` on wall placement coordinates (`walls.py:108`)

Malformed input crashes with a raw 500 instead of a clean 400 `HomeAssistantError`/`web.HTTPBadRequest`.

### 13. Still no upload size limit, and it now also covers Library uploads (`http_api.py`, `library.py:133`, `library_http.py`) — unfixed since the v0.1.6 review

The original finding (raw image uploads) is still open, and the same unbounded-body pattern now also applies to the newer multi-file Library upload endpoint.

### 14. ~~Options-flow "name" field is silently ignored~~ — RESOLVED

**Resolved** by the dashboard-consolidation work: the dead `CONF_NAME` field was removed from `FraimicOptionsFlow`'s schema entirely. Renaming now happens through the panel's frame-settings menu, which calls the `config_entries/update {title}` WS command — the mechanism that actually propagates to the entry title and device name.

### 15. `FraimicChargingSensor` is still a plain `SensorEntity`, not `BinarySensorEntity` (`sensor.py:183-208`) — unfixed since the v0.1.6 review

`native_value` still returns the strings `"True"`/`"False"`, blocking `binary_sensor.is_on` automations and polluting history.

### 16. ~~Ad-hoc `aiohttp.ClientSession()` instead of the managed session~~ — RESOLVED

**Resolved** alongside #5: `scan_subnet` and `find_frame_by_device_key` now take a required `session` parameter, and every former ad-hoc `aiohttp.ClientSession()` site (`async_step_dhcp`, both `async_step_user` branches, `_async_use_device`) passes `async_get_clientsession(self.hass)`. Because the shared connector has finite connection limits, `scan_subnet` also gained a `Semaphore(64)` bound with the 0.5 s probe timeout applied inside acquisition — without it, probes queued behind the connector limit would burn their timeout before sending a packet and silently miss live frames.

### 17. `assert` used for a production sanity check (`image_converter.py:105`) — unfixed since the v0.1.6 review

Disabled under Python `-O`. Replace with an explicit `if ...: raise RuntimeError(...)`.

### 18. Bare `except Exception: pass` around EXIF handling (`image_converter.py:457-458`) — unfixed since the v0.1.6 review

Swallows `MemoryError`, `OSError`, and genuine bugs, not just "older Pillow" as the comment claims. At minimum log at DEBUG.

---

## Low / Style

### 19. `_LOGGER` still defined but unused in `sensor.py:27` — unfixed since the v0.1.6 review

### 20. Empty `if TYPE_CHECKING: pass` block still present in `config_flow.py:44-45` — unfixed since the v0.1.6 review

### 21. Unused `TYPE_CHECKING` import in `sensor.py:6`

Imported but no `if TYPE_CHECKING:` block exists anywhere in the file — new since the last review.

### 22. `DEFAULT_PORT` remains unused repo-wide (`const.py:10`)

Confirmed via repo-wide search — port 80 is assumed implicitly everywhere host URLs are built. (`CONF_MODE`/`MODE_*` at lines 26-32 are intentionally forward-looking per CLAUDE.md — not flagged.)

### 23. Missing blank line before `__init__` in `FraimicBatterySensor` (`sensor.py:120` area) — unfixed since the v0.1.6 review

Every other sensor class in the file has the blank line; this one doesn't.

### 24. `os.path.isfile(abs_path)` called directly on the event loop in `_handle_send_image` (`__init__.py:435`)

Not wrapped in an executor job. Normally fast, but worth folding into the same executor call as the Pillow conversion right after it for consistency.

### 25. `_register_services`'s `has_service` guard is check-then-act, not atomic (`__init__.py:263-264, 290-291`)

Two config entries setting up concurrently at HA startup could both see `False` and both register. Harmless in practice (the second registration overwrites the first with an equivalent handler) but worth a comment if anyone's ever debugging duplicate-registration log noise.

### 26. Wall drag can leave an orphaned ghost element in the DOM (`fraimic-panel.js:4463-4498` `_wallBeginDrag`)

A second `pointerdown` before the first drag's `pointerup` overwrites `this._wallDrag` without cleaning up the first drag's ghost element, which is never `.remove()`d. Needs overlapping pointer inputs (multi-touch/stylus+mouse) to trigger — low frequency, but a real, traceable leak.

### 27. Frontend version constants are stale and inconsistent with the manifest (`fraimic-card.js:14`, `fraimic-panel.js:10`)

`CARD_VERSION = '0.1.4'` and `PANEL_VERSION = '0.10.2'` vs. `manifest.json`'s `0.12.25`. `PANEL_VERSION` is shown to users in a modal footer, so it actively misleads anyone trying to match panel version to integration version for support purposes.

### 28. Wall placements aren't cleaned up when a frame's config entry is deleted (`walls.py`)

Orphaned placement records referencing a nonexistent frame. Low impact since walls don't drive sends directly.

### 29. Cloud library backends always rewrite the remote manifest on `async_save_bin` (`library.py:445`)

`LocalLibraryBackend` has an optimization to skip the write when nothing changed; the cloud backends don't, costing an extra round trip per save.

---

## Positive Notes

- Both Critical fixes from the v0.1.6 review — `_safe_media_join` (`__init__.py:353-368`) and `_resize_cover_centered` (`image_converter.py:128-153`, formerly `_resize_with_letterbox`) — are correct and well-documented about *why* they work the way they do, including the deliberate choice to keep cover/crop behavior rather than letterbox.
- The v0.1.6 review's IP-based `unique_id` finding is fixed: `config_flow.py:284-293` now anchors on the frame's persistent `device_key`, falling back to IP only for old firmware.
- `frame_types.py`'s `_validate_registry()` fails loudly at import time if two frame types share a resolution but disagree on byte layout — a good defensive check against silent on-hardware image corruption.
- The fast vectorized packing path is verified byte-identical to the legacy per-pixel path (`scripts/verify_packing.py`), with the module docstring documenting both panel byte layouts against real reference implementations rather than guessing.
- `LocalLibraryBackend` and the cloud backends correctly serialize manifest read-modify-write via `asyncio.Lock` — exactly the race class a past incident (documented in CLAUDE.md) warned about.
- All HTTP views correctly set `requires_auth = True` except the OAuth callback, which is justifiably open (browser redirect) and protected by a one-time state token.
- Blocking file/Pillow work is consistently offloaded via `hass.async_add_executor_job` throughout the newer library/scene-pack code, and all frame communication uses `async_get_clientsession` — the deviation is confined to config-flow discovery helpers (Medium #16).
- `_esc()` is used consistently and correctly across every area of the panel, including the newest scene-pack and wall code — no unescaped user-controlled string reaching `innerHTML` was found anywhere in ~5400 lines.
- The `CSS.escape` shadowing bug from `129835b` is fixed and not reintroduced anywhere else; the wall tile lookup explicitly documents why it avoids `CSS.escape` in that closure.
- Global listener lifecycle cleanup (`71c1b17`) is solid for everything except the two async-fetch gaps above (#7) — every `window`/`document` listener, including the newer wall-drag and crop-editor registrations, is tied to `this._abort.signal` and covered by `tests/panel/lifecycle.spec.js`.
- The wall image picker's staleness-token pattern (`_wallImagePickerToken`) is exactly the right fix for the album-switch and crop-editor races above — it just needs to be applied to those two other call sites.
- `fraimic-card.js` remains small and clean, correctly revoking previous object URLs before reassignment.
