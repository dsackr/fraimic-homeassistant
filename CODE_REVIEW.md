# Digital Frames HA Integration — Code Review

**Reviewed:** v0.12.129
**Date:** 2026-07-19
**Files:** every file under `custom_components/digital_frames/` (34 Python
modules, ~15.7k lines; `digital-frames-panel.js`, ~10.6k lines;
`digital-frames-card.js`, ~1.6k lines) — a full re-review, not a diff.

---

## Summary

The previous review (v0.12.25) is 100+ releases stale; this one starts from
scratch and re-verifies every prior finding against the current code rather
than assuming it's still accurate. Result: **one prior Critical is fixed
outright** (the `scene_packs.py` uninstall `NameError`), but it was replaced
by an equivalent architectural bug in the same method; **three prior
High-severity panel-JS races are still open, unchanged**; and one prior
Medium (`DigitalFramesChargingSensor`) is still open, unfixed since the
*original* v0.1.6 review — now three reviews running.

The product has grown substantially since the last review (Meural and
Samsung drivers, Gallery/Live content platform, marketplace foundations,
domain rename to `digital_frames`) and the new code is generally
disciplined — good exception hierarchies in the polling path, careful
manifest locking, a real path-traversal guard in the self-update zip
extractor, consistent use of `hass.async_add_executor_job` for blocking
work. But this pass found **new Critical-severity bugs the last review
didn't catch**: a reflected XSS in an intentionally-unauthenticated OAuth
callback, a live path-traversal class in the library's `.bin` cache reached
by both the send and delete endpoints, a self-update path with no rollback
on partial failure that can brick the integration, and — the one most in
keeping with this codebase's own stated biggest risk ("garbled image on the
physical frame, no exception, invisible until someone looks at hardware")
— Live text/agenda skill renders silently skip the rotation-to-native-buffer
step that ordinary photo sends always apply, for any frame with a
non-native orientation lock.

All findings below were verified by reading the actual current code (not
inferred from names/docstrings); several were additionally confirmed by
executing the relevant function directly. Every file/line reference was
checked against the repository at the reviewed commit.

---

## Critical

### 1. Reflected XSS in the unauthenticated Google Drive OAuth callback
`library_http.py:909-1001` (`DigitalFramesLibraryGoogleOAuthCallbackView`)

```python
requires_auth = False
...
error = request.query.get("error")
if error:
    return self._page(f"Google declined: {error}", ok=False)
...
@staticmethod
def _page(message: str, ok: bool) -> web.Response:
    ...
    html = (
        "<!DOCTYPE html><html><body ...>"
        f"<h2 style=\"color:{color}\">{message}</h2>"
        "</body></html>"
    )
    return web.Response(text=html, content_type="text/html", status=...)
```

`requires_auth = False` here is legitimate and well-documented (this is a
plain browser redirect target with no `Authorization` header available;
it's protected by a one-time `state` token instead) — but the `error` query
parameter is reflected into the HTML response with **zero escaping**, before
any `state` check even runs. A same-origin URL like
`GET /api/digital_frames/library/oauth/google/callback?error=<script>...</script>`
requires no prior authentication and executes in the HA origin for anyone
who opens it while logged in — classic reflected-XSS-to-session-compromise,
on an endpoint specifically designed to be reachable pre-auth.

**Fix**: `html.escape(message)` before interpolation (or move to an escaped
templating call) — apply everywhere `_page()` is called with a value that
originates from the request.

### 2. `image_id` path traversal into the library `.bin` cache — send and delete paths
`library.py`: `_bin_path` (459-474), `async_get_bin_for_send` (1959-2003),
`_delete_image_sync` (588-612). `library_http.py`: `DigitalFramesLibrarySendView.post`
(320-413, `image_id` read from a POST body field at line 335 with only a
truthy check), `DigitalFramesLibraryImageView.delete` (~202-210).

```python
def _bin_path(self, image_id, width, height, variant="", codec_id="") -> str:
    res = _bin_res_key(width, height, variant)
    if codec_id:
        return os.path.join(self._root, "bin", res, codec_id, f"{image_id}.bin")
    return os.path.join(self._root, "bin", res, f"{image_id}.bin")
```

Unlike `_original_path_for`, which runs the filename through
`_safe_filename()`, `_bin_path` interpolates `image_id` with **no
sanitization at all** and no manifest-membership check. Confirmed the send
path: `async_get_bin_for_send` (1998-2003) checks the on-disk `.bin` cache
**before** any manifest lookup —

```python
if pack_method is None:
    cached = await self._backend.async_get_bin(image_id, width, height, spec.variant, codec_id)
    if cached is not None:
        return cached
```

— so a crafted `image_id` (the send endpoint reads it from a multipart POST
*body* field, not a URL path segment, so it isn't constrained by aiohttp's
route-segment matching and can contain `/`/`..` freely) that resolves via
traversal to any real `<...>.bin`-suffixed file returns that file's raw
bytes, which are then sent to whatever frame the same request names. The
delete path (`_delete_image_sync`) has the identical unsanitized
interpolation, reachable from the URL path segment `{image_id}` (more
constrained, but not proven immune to `%2F`-style encoding bypasses in
aiohttp's route matching).

**This is materially worse on the Dropbox backend** (`_bin_path` at
939-950): there the "path" is a Dropbox API path, so a successful traversal
read/delete can potentially reach anywhere in the user's entire Dropbox
account, not just the library folder. The **Google Drive backend is not
affected** — it looks the image up in the manifest first and only ever
resolves an opaque Drive file id, never a raw path — that's the correct
pattern and should be back-ported to Local/Dropbox.

**Fix**: validate `image_id` against the actual format produced by uploads
(`uuid4().hex[:12]`, i.e. `re.fullmatch(r"[0-9a-f]{24}", image_id)`) at the
HTTP layer, and/or require manifest membership before any `_bin_path`/backend
`async_get_bin`/`async_save_bin`/`async_delete_bin` call. Same fix needed for
the local thumbnail path (`_thumb_path`, reachable via `?thumb=`, lower
severity since the constructed filename shape is narrower but still
unvalidated).

### 3. Failed/partial self-update extraction has no rollback — can brick the integration
`update.py:691-738` (`_extract`, called from `_install_from_zipball`)

```python
if os.path.isdir(dest):
    bak = os.path.join(backup_root, f"{_COMPONENT}.bak.{expected_version or 'prev'}")
    ...
    shutil.move(dest, bak)          # old install moved out of the way

os.makedirs(dest, exist_ok=True)
for info in zf.infolist():
    ...
    with zf.open(info) as src, open(out_path, "wb") as out:
        shutil.copyfileobj(src, out)   # no try/except around this loop
```

The existing install is moved to a backup directory, then every file is
written in a loop with **no exception handling inside the loop**. If any
single write fails partway (disk full, permission error, interrupted
download producing a corrupt zip mid-read), the exception propagates out of
`_extract()`, is caught only by `_install_from_zipball`'s generic wrapper
(733-738, re-raises `UpdateError`) — **the backup is never restored**. HA is
left with a half-written `custom_components/digital_frames/` and no old
copy to fall back to; the integration fails to load on next restart with no
automated recovery path (the admin has to manually copy
`.storage/fraimic_update_backup/digital_frames.bak.<version>` back).

**Fix**: wrap the write loop in try/except; on any failure,
`shutil.rmtree(dest)` then `shutil.move(bak, dest)` to restore the prior
good state before re-raising.

### 4. Post-install version check can silently mask the failure above
`update.py:554` and `:645` (`install_update`, `_try_hacs_install`)

```python
disk = await get_disk_version(hass) or target
...
if disk and _norm_version(disk) != _norm_version(target):
    _LOGGER.warning("Post-install disk version %s does not match target %s", disk, target)
```

If extraction leaves `manifest.json` missing or unreadable (exactly finding
#3's failure mode, or any zip whose entry ordering skips it),
`get_disk_version()` returns `""`, and this line substitutes `target`
**before** the mismatch check ever runs — so the check that exists
specifically to catch this can never fire in the one case it matters most,
and the returned/logged status reports the install as matching `target`
even though the on-disk manifest doesn't actually say that.

**Fix**: check the raw `get_disk_version()` result for the mismatch/failure
report; don't substitute `target` before that comparison.

### 5. Live text/agenda skill renders skip the rotation-to-native-buffer step — garbled output on any orientation-locked Spectra frame
`panel_codec.py:329-394` (`text_skill_payload_for_codec`), `helpers.py:117-164`
(`render_spec_for_entry`), `skills.py:463-486, 858-879`.

Ordinary photo sends compose at the frame's *effective* (possibly
w/h-swapped) canvas size and then explicitly rotate the composed image back
into the panel's *native* buffer orientation before packing —
`image_converter.py`'s `_process` does this unconditionally. Live skills
don't:

- `render_spec_for_entry` (`helpers.py:140-164`) computes `eff_w, eff_h` by
  swapping native width/height whenever the user's orientation lock
  (`CONF_ORIENTATION`, a standard per-frame option) disagrees with the
  panel's native buffer orientation, and sets a nonzero `rotation` (90/270)
  for that case.
- `_async_render_text` (`skills.py:477-486`) passes `spec.width, spec.height`
  — the **effective**, already-swapped dimensions — to the external xOTD
  renderer as the canvas it draws and packs `xotd.bin` at.
- `text_skill_payload_for_codec` (`panel_codec.py:371-394`) is then given
  `spec.rotation` explicitly, but in the Spectra (non-JPEG) branch, rotation
  is applied **only to the RGB preview PNG** (`_image_from_rgb_png()`,
  lines 365-369) — the actual wire payload is returned completely untouched:
  `return spectra_bin, preview` (line 394).

Net effect: for any frame with `rotation != 0` (orientation locked opposite
its native buffer — not a rare configuration), the `.bin` sent to the panel
is packed at the *effective* (swapped) width×height, never rotated back into
the *native* row/column layout the panel's raster actually expects. Total
byte count still matches (a swap doesn't change `w*h`), so no length-mismatch
exception fires — the failure is silent, exactly the "wrong picture on real
hardware, invisible until someone looks at it" class this codebase's own
docs call out as the highest-risk failure mode. Ordinary photo sends to the
same frame render correctly, so this reads as a skills-only regression.
Confirmed no test in `tests/python/unit/test_panel_codec.py` exercises
`text_skill_payload_for_codec` with a non-zero rotation.

**Fix**: apply `rotation` to the composed Spectra image before/while packing
in the non-JPEG branch (mirroring `_process`), or have the external renderer
draw directly in native orientation using `rotation` as an input.

### 6. Samsung (PNG codec) frames given a Live skill silently receive raw Spectra6 bytes mislabeled as valid payload
`panel_codec.py:371-394`

```python
if codec_id == CODEC_JPEG_Q90:
    ...
    return wire, _encode_preview_png(image)

# Spectra wire payload
...
return spectra_bin, preview
```

Only `CODEC_JPEG_Q90` (Meural) gets an image-based re-encode. `CODEC_PNG`
(Samsung, assigned in `panel_codec_for_entry`) falls through to the "Spectra
wire payload" branch along with everything else, so a Samsung frame
assigned any text/agenda Live skill gets the Spectra6 nibble-packed bytes
returned as-is — no exception anywhere in the call chain (nothing in
`schedules.py`'s target validation, `skills_http.py`'s send view, or
`skills.py` blocks a Samsung driver from being a skill target). The "send"
reports success while the frame receives corrupted non-PNG bytes. Confirmed
no test exercises `text_skill_payload_for_codec` with `CODEC_PNG`.

**Fix**: add an explicit `CODEC_PNG` branch (compose RGB, rotate, PNG-encode
— mirroring the JPEG branch) and raise `SkillError` on failure instead of
silently falling through.

---

## High

### 7. `send_image` service still accepts an arbitrary absolute filesystem path — the media-root sandbox has a gap
`__init__.py:681-719` (`_resolve_media_path`), specifically the fallthrough at
line 718.

```python
if media_content_id.startswith("media-source://"):
    ...
if media_content_id.startswith("/media/"):
    ...
return media_content_id, False
```

`_safe_media_join` correctly constrains the two recognized shapes to
`hass.config.media_dirs["local"]`, but `_SEND_IMAGE_SCHEMA` validates
`media_content_id` with plain `cv.string` — anything not matching either
prefix (e.g. `/config/secrets.yaml`, any other HA-process-readable path)
falls through **unchecked** and is fed directly to
`os.path.isfile`/`encode_path_for_panel_with_preview`. Any HA
user/automation able to call `digital_frames.send_image` (services are
callable by non-admin users by default; no `call.context` admin check here)
can probe filesystem existence and have any readable image file rendered
and sent to a frame they control — an arbitrary local file read scoped to
image content, defeating the purpose of the sandboxing that exists for the
other two shapes.

**Fix**: reject the fallthrough outright (`raise HomeAssistantError(...)`)
instead of returning the raw string unchanged.

### 8. Meural orientation-follow double-sends every postcard
`meural_coordinator.py:240-260` (`_async_maybe_follow_device_orientation`),
`select.py:165-203` (`MeuralOrientationSelect.async_select_option`),
`__init__.py:562-598` (`_async_update_listener`)

Both the coordinator's gsensor-follow path and the orientation select
entity call `hass.config_entries.async_update_entry(options=...)` and then
call `coordinator.async_redisplay_last()` **directly**. But
`async_update_entry` also fires every registered listener for that entry —
including the globally-registered `_async_update_listener` (`__init__.py`),
which independently detects the same `CONF_ORIENTATION`/
`CONF_ORIENTATION_FOLLOW_DEVICE` change and calls the very same
`coord.async_redisplay_last()` as a second, separately-scheduled task. The
coordinator's `_redisplay_lock` only serializes the two calls — it doesn't
dedupe them — so both actually run to completion: two full library
re-encodes and two postcard POSTs for one orientation change (a visible
double-redraw flash, and double the network/CPU work).

**Fix**: pick one trigger. Either stop calling `async_redisplay_last()`
directly at the two call sites and let `_async_update_listener` be the sole
source of truth for options-driven redisplay, or have the listener skip
firing when the entry just redisplayed itself (e.g. a short-lived
in-flight/recently-done guard on the coordinator).

### 9. `async_send_image_or_queue`'s exception guard misses `ClientResponseError` — stuck pending-send state, raw traceback in two service handlers
`coordinator.py:269-303`

```python
try:
    await self.async_send_image(image_bytes)
    await self._clear_pending_if_current(token)
except (aiohttp.ClientConnectionError, TimeoutError):
    ...
finally:
    self._flushing = False
```

`async_send_image` calls `response.raise_for_status()`, which raises
`aiohttp.ClientResponseError` for any non-2xx frame response.
`ClientResponseError` and `ClientConnectionError` are **siblings** under
`aiohttp.ClientError`, not parent/child — this except clause does not catch
it. Contrast with `_async_update_data` in the same file, which correctly
handles connection errors, response-status errors, and a generic fallback
as three separate tiers — the polling path gets this right, the send path
doesn't. On a non-2xx response: `pending_send` (already persisted before
the network call) is never cleared, `update_interval` stays pinned at the
fast-poll interval until the next poll's flush retries the same rejected
payload, and the raw exception propagates uncaught out of the two callers
that wrap this with no try/except at all — `__init__.py`'s
`_handle_send_image` and `_handle_generate_ai_image` service handlers.

**Fix**: broaden to `except aiohttp.ClientError` (matching the pattern the
Meural/Samsung drivers already use correctly), and wrap the two unguarded
service handlers the same way `http_api.py`/`library_http.py` already do.

### 10. Scene pack uninstall still has the failure shape the "fixed" `NameError` bug left behind
`scene_packs.py:506-530` (`async_uninstall_pack`)

The literal `NameError` from the prior review is gone — `pack =
await self.async_get_pack(pack_id)` (line 529) does assign `pack` before
use now. But this line is a **network fetch of the remote catalog**, and it
still runs *after* the scene has already been irreversibly deleted two
lines above (`await self._scenes.async_delete_scene(...)`, line 524). If the
catalog is unreachable, returns non-200, or (very plausibly over time) no
longer lists this `pack_id`, `async_get_pack` raises `ScenePackError` — the
scene is already gone, `self._installed[pack_id]` is never cleared, and
every retry fails identically for as long as the catalog condition holds.
Notably `installed.get("album")` (always populated at install time) makes
this network round-trip unnecessary in the first place — `pack["name"]` is
only used as a fallback that essentially never triggers.

**Fix**: don't fetch the pack from the network for uninstall at all (use
`installed.get("album")` directly), or wrap the fetch in try/except with a
graceful fallback so uninstall never depends on the remote catalog still
listing the pack.

### 11. Wall auto-placement can place a new frame directly on top of an existing tile
`walls.py:154-176` (`_append_placement`)

```python
row, col = divmod(len(wall.placements), _MAX_FRAMES_PER_ROW)
y = _MARGIN_TOP + row * _CELL
if col == 0:
    x = _MARGIN_LEFT
else:
    ...  # scans existing same-row tiles to avoid collision
```

The `col == 0` branch assumes "count is a multiple of 4 ⇒ this is a fresh
row" and places at a fixed `x` with **no occupancy check** — unlike the
`col != 0` branch, which correctly scans real positions. Ordinary usage
triggers this: start with 5 auto-placed frames (row 0: 4 tiles, row 1: 1
tile). Remove any one of the first four (`async_prune_entry`, called from
`__init__.py` on entry removal) — `wall.placements` now has 4 entries. Add a
new frame: `divmod(4,4) == (1, 0)` → placed at exactly the same `(x, y)` as
the surviving 5th frame, which was never moved. No dragging or manual
layout needed to hit this.

**Fix**: give the `col == 0` branch the same occupancy scan the `col != 0`
branch already has (or derive row occupancy from actual placement
coordinates rather than from `len(wall.placements)`).

### 12. Cover-crop resize truncates instead of rounding up — a real, reproducible 1px unfilled edge on registered panel resolutions
`image_converter.py:128-153` (`_resize_cover_centered`)

```python
scale = max(target_width / orig_w, target_height / orig_h)
scaled_w = int(orig_w * scale)
scaled_h = int(orig_h * scale)
```

`int()` truncates toward zero; floating-point error routinely lands the
scaled dimension a fraction under the exact target, so the resized image is
1px short on the governing axis. The canvas is pre-filled white and
`paste()` doesn't stretch to compensate, so a stray white row/column survives
into the final quantized/packed image. **Reproduced directly** against the
real registered 1200×1600 panel profile: a 344×193 source produces a
1200×1599 resized canvas, leaving the entire bottom row white. This is the
default (non-manual-crop) pipeline used by every ordinary send.

**Fix**: `math.ceil` instead of `int()` for `scaled_w`/`scaled_h` — the
existing centered crop already trims any resulting 1px overage, so this is a
strict improvement with no other side effect.

### 13. Panel JS — thumbnail/crop-editor blob URLs leak on dispose mid-fetch (open since the last review, unfixed)
`digital-frames-panel.js`, `_dispose()` (~2120-2152), `_fetchThumb` (~5247-5275),
`_openEditor`'s full-size fetch (~5849-5861)

`_dispose()` revokes every blob URL tracked in `_thumbUrls` and resets the
tracking containers to fresh objects, but neither in-flight fetch is tied to
`this._abort.signal`, and neither checks a disposed flag before calling
`URL.createObjectURL`. Navigating away from the panel while a thumbnail or
the crop editor's full-size image is still loading lets that continuation
run anyway, writing a fresh, never-revocable blob URL onto whatever object
exists post-dispose — a leak on every visit where a slow image is caught
mid-load, and HA recreates this panel element per navigation rather than
reusing it.

**Fix**: pass `{ signal: this._abort.signal }` to both fetches, or check a
disposed flag immediately before `createObjectURL` and revoke-on-arrival if
set.

### 14. Panel JS — `_openAlbum` has no staleness guard (open since the last review, unfixed)
`digital-frames-panel.js`, `_openAlbum`/`_loadLibrary` (~4911-4949)

```js
async _openAlbum(name) {
  this._currentAlbum = name;
  await this._loadLibrary(name);
  this._renderLibrary();
}
```

`_loadLibrary` unconditionally overwrites `this._library` with no token
check. Clicking two album tiles quickly races two fetches; whichever
resolves last wins on `_library`, while `_currentAlbum` (set synchronously)
can end up naming a different album — title and grid mismatch. The correct
fix (a staleness token) already exists elsewhere in this file (the wall
image picker's `_wallImagePickerToken`, confirmed still working) and has
still not been applied here.

**Fix**: apply the same token pattern used by the wall image picker.

### 15. Panel JS — crop editor can silently save a crop computed from the wrong image (open since the last review, unfixed)
`digital-frames-panel.js`, `_openEditor`/`_closeEditor` (~5780-5879)

`_openEditor` sets `this._editorState` synchronously, then awaits a
fetch/decode before writing `naturalW`/`naturalH` onto that same object;
`_closeEditor` nulls the state and revokes the blob but doesn't cancel or
invalidate an in-flight `_openEditor` call. Closing the editor and reopening
it for a different image while the first image's fetch is still pending
lets the first fetch's continuation later overwrite the *current* editor's
blob URL and dimensions with the stale image's data — visibly swapping the
picture back while the actual save target (`image_id`) stays the current
one, so a crop computed from image A's dimensions gets persisted against
image B. No test covers the crop editor.

**Fix**: capture a token or `image.image_id` at the top of `_openEditor` and
no-op the post-fetch continuation if `this._editorState` no longer matches
it (same pattern needed for #14).

### 16. Panel JS — wall drag/marquee still leaks a ghost element on overlapping pointer input (renumbered from the last review, unfixed)
`digital-frames-panel.js`, `_wallBeginDrag` (~7689-7762), `_wallBeginMarquee` (~6681-6699)

Neither function guards against a pre-existing `this._wallDrag`/
`this._wallMarquee` before overwriting it. A second `pointerdown` before the
first drag's `pointerup` — plausible on the touchscreen tablets this
dashboard is commonly mounted on — creates a second ghost/marquee element
and overwrites the tracking field, permanently orphaning the first one (only
`_dispose()` cleans up whatever the field *currently* points to) and
corrupting which drag `pointerup` finalizes.

**Fix**: finalize/cancel any existing drag or marquee before starting a new
one, or scope drag state by `pointerId` with `setPointerCapture`.

### 17. Card JS — crop editor's "Save & Send" leaves the card stuck in preview state
`digital-frames-card.js`, `_cropSaveSend()` (~1491-1539) vs. `_send()` (~1284-1293)

`_cropSaveSend()` never calls `this._unstage()` on success, unlike `_send()`.
Reachable via ordinary use (Photos → pick an image → Crop → Save & Send
inside the overlay): the image is sent immediately, but `this._staged` stays
set, so the Send/Cancel bar stays visible, the badge keeps showing PREVIEW
instead of ON FRAME, and `_renderMedia()`/the media click handler both
short-circuit on `this._staged` — the card shows stale UI until the user
clicks Send again or Cancel.

**Fix**: call `this._unstage()` in the same success branch, mirroring
`_send()`.

### 18. Card JS — `setConfig()` rebuild doesn't reset in-flight staged/crop state
`digital-frames-card.js`, `setConfig`/`_build` (~308-311, 351-789)

`_build()` always replaces the shadow DOM from scratch but never resets
`this._staged`/`this._crop`. Home Assistant's card-editor live preview calls
`setConfig()` on every config change (e.g. every keystroke in the editor's
Name field). Staging a photo or opening Crop, then typing in the editor,
rebuilds the DOM to its default hidden state while `_staged`/`_crop` remain
truthy — `_renderMedia()` and the media click handler keep no-opping with no
visible control left to reach `_unstage()`; the card is stuck until reload.

**Fix**: reset `_staged`/`_pickerMode`/`_crop` (revoking associated blob
URLs) whenever `_build()` tears down the DOM, or skip the rebuild when the
relevant config fields haven't actually changed.

### 19. Card JS — no `disconnectedCallback` anywhere; blob URLs and global listeners outlive the element
`digital-frames-card.js` (confirmed via full-file grep)

Neither `DigitalFramesCard` nor its editor defines
`disconnectedCallback`/`connectedCallback`. HA recreates custom card
elements on dashboard/view changes; any of `_mediaBlobUrl`,
`_stagedPreviewUrl`, `_cropImgUrl` left set, plus the `window` `resize`/
`pointermove`/`pointerup` listeners registered while the crop overlay or a
crop drag is active, leak until page reload if the element is removed at
the wrong moment.

**Fix**: add `disconnectedCallback()` that revokes all three blob URLs and
removes the three `window` listeners (mirrors the panel's own
`71c1b17` fix, which this card never received).

### 20. Cloud library backends silently treat failed remote deletes as success
`library.py`: `DropboxLibraryBackend.async_delete_image` (1131-1159),
`GoogleDriveLibraryBackend._delete_file` (1445-1448)

Both discard the delete response with no status check at all (contrast with
`Dropbox`'s own `async_delete_bin`, two methods above, which correctly
checks `resp.status`) and then unconditionally remove the image from the
manifest regardless of whether the remote delete actually succeeded. A
transient Dropbox/Drive failure (expired token, rate limit, 5xx) orphans the
file remotely while the app forgets it ever existed — no error surfaced, no
way to retry, because the only record of it is gone.

**Fix**: check `resp.status` in both places and raise `LibraryBackendError`
on failure before updating the manifest, matching the pattern already used
correctly elsewhere in the same file.

---

## Medium

21. **Blocking filesystem I/O directly on the event loop** — `__init__.py`
    `_download_media_to_temp` (667-678, `tempfile.mkstemp`/`fh.write` not in
    an executor), `_handle_send_image` (`os.path.isfile` at 943, `os.remove`
    at 973). `library.py`'s `DropboxLibraryBackend`/`GoogleDriveLibraryBackend`
    `.async_get_local_path` (`os.makedirs`/`os.path.isfile` not offloaded,
    unlike the rest of the file).
22. **Unhandled network exceptions surfacing raw** — `__init__.py`
    `_fetch_media_bytes` (646-664) only converts a non-200 status to
    `HomeAssistantError`; a connection failure/timeout from `session.get()`
    propagates unmodified through the send-image and generate-AI-image
    service paths.
23. **Stale service registrations after last frame removed** — `__init__.py`
    (~526-532) removes 7 services on last-entry teardown but omits
    `generate_ai_image` and `auto_tag_all`, which stay callable (and then
    fail deeper/less clearly) after the domain considers itself torn down.
24. **Inconsistent exception handling across Assist intents** — `intent.py`:
    `DigitalFramesGenerateAIImageIntent`/`DigitalFramesSendSkillIntent` only
    catch `HomeAssistantError`; `DigitalFramesShowImageIntent` correctly
    catches broad `Exception`. The first two leak raw errors instead of a
    clean Assist "failed to handle" response.
25. **Meural/Samsung entities never go `unavailable` when offline** —
    `light.py`'s `MeuralBacklightLight.is_on` (66-70) returns `True` for an
    unreachable frame (only `False` when explicitly `sleeping`); neither
    driver's coordinator raises `UpdateFailed` on unreachable (a deliberate,
    documented choice to keep the config entry loaded), but no entity
    overrides `available` to compensate, so a fully offline Meural Canvas
    shows its backlight as **on** indefinitely, and the camera keeps serving
    a stale thumbnail with no offline indication. Contrast: the Fraimic
    driver correctly raises `UpdateFailed`, so its entities correctly go
    unavailable — the gap is specifically the other two drivers.
26. **Orientation-lock push failures silently swallowed** — `select.py`
    (~181-182, ~190-193), `except Exception: pass` around
    `async_set_device_orientation`; a failed push to the physical Canvas
    (offline, timeout) still reports the UI selection as successful with no
    log, no retry.
27. **Samsung MDC packet length boundary is off by 3** — `samsung.py:37-42`
    and the mirrored guard in `samsung_coordinator.py:177-181` reject URLs
    `> 255` bytes, but `data_len = len(url_bytes) + 3` is itself packed into
    a single byte — a URL of 253-255 bytes passes the guard and then crashes
    `bytes([...])` with `ValueError: bytes must be in range(0, 256)`
    instead of the intended clear error message. Correct boundary is `> 252`.
28. **`_flushing` guard isn't scoped per send** — `coordinator.py` (~269,
    299-300, 319-321): the anti-double-flush boolean is a single field on the
    coordinator, not scoped to the in-flight call/token. Two concurrent sends
    to the same frame can let one call's `finally: self._flushing = False`
    clear the guard while the other's upload is still in flight, letting a
    routine poll's flush-check re-send the second call's payload a second
    time.
29. **Subnet self-heal rescan has no generation guard** —
    `coordinator.py` (~460-497 vs. ~503-516): the pending-send logic uses a
    `token` specifically so a slow, superseded write can't clobber a fresher
    one; the IP self-heal rescan has no equivalent, so a slow full-subnet
    sweep completing after a faster DHCP-driven host update can overwrite the
    correct host with a stale result.
30. **Album batch operations (add/rename/delete) read-then-write outside the
    manifest lock** — `library.py` `_async_apply_album_transform`
    (2181-2194) reads `async_list_images()` unlocked and computes the new
    album lists from that snapshot; only the later bulk-write step takes
    `_manifest_lock`, so a concurrent album mutation committed in between can
    be silently clobbered by the stale-computed update.
31. **Background backfill can skip pre-warming a codec that shares geometry
    with an already-cached different codec** — `library.py`
    `has_resolution` (254-255) checks `[width, height]` only, with no
    `codec_id` — contradicts the cache design's own stated intent (Meural
    JPEG and Spectra at the same geometry must not share a cache slot). Not
    data-corrupting (on-the-fly send-time conversion still keys correctly by
    codec) but silently defeats the background pre-warm for any install
    mixing frame types at the same resolution.
32. **No explicit upload size limit** — `library_http.py`'s
    `DigitalFramesLibraryUploadView` (110-151) and `http_api.py`'s
    `DigitalFramesSendImageView` (~249-282) both rely entirely on HA's global
    `client_max_size`; neither view imposes its own per-file/request cap
    before reading the full body into memory. The direct-upload view is also
    `requires_auth = True` but **not admin-gated** — any authenticated
    non-admin dashboard user can reach it.
33. **Live skill fan-out consistency isn't actually enforced for
    non-deterministic content** — `skills.py`'s `_async_fetch_content_fields`
    (423-461) caches only `skill.config` (static per day), not the result of
    whatever random fetch the *external* pinned renderer performs per
    invocation — so a "Joke of the Day" fanned to N frames can plausibly get
    N different jokes from N concurrent subprocess invocations, the exact bug
    class the cache's own docstring says it prevents. (Caveat: the renderer's
    source isn't vendored in this repo, so whether it self-dedupes couldn't
    be fully confirmed from here — flagged as a real gap in this repo's own
    guarantee either way.) `_async_fetch_image_feed`/`_async_pick_image_album`
    (750-827) have no memoization at all — every fan-out call re-fetches and
    re-uploads a new library entry, risking API rate limits (NASA APOD's
    `DEMO_KEY`) and unbounded duplicate accumulation in the library.
34. **Schedules with an unparsable trigger never reach a "broken" state** —
    `schedules.py` `_arm` (~442-449) and `_async_fire_missed` (~235-254) just
    log and skip on a `ScheduleError` from parsing `once.at`, unlike the
    target-deleted path, which explicitly transitions to
    `STATUS_TARGET_MISSING` + disables. A corrupted `at` value (bad
    migration/manual storage edit) leaves a schedule looking enabled/pending
    forever, silently skipped by every restart's catch-up sweep.
35. **Skill content cache is never invalidated on edit** — `skills.py`
    `async_save_skill` (314-351) never clears `_content_cache`; editing a
    skill's config and firing/sending it within the 1800s TTL window returns
    pre-edit content.
36. **Update status check has a persistence side effect** — `update.py`
    `check_for_update` (~274-292) can trigger `_sync_hacs_after_install`,
    which writes HACS's `.storage` data as a side effect of what's nominally
    a read-only status check (admin-gated, so not a security issue — a
    "GET shouldn't mutate" design smell).
37. **`_version_tuple` isn't true semver comparison** — `update.py:80-97`;
    `"1.2.0" > "1.2"` due to Python tuple-length comparison. This project's
    tags are consistently 3-part, so unlikely to trigger today, but any
    dot-count mismatch between a GitHub tag and the on-disk manifest would
    produce a persistent, never-resolving "update available" state.
38. **Card JS — `_renderMedia()` has no staleness guard** —
    `digital-frames-card.js` (~913-966): a slow-resolving fetch for an older
    image can overwrite a newer, already-painted image if two refresh cycles
    race, showing the wrong photo for up to ~30s until the next refresh
    self-corrects.
39. **Card JS — `getStubConfig()`'s platform check can never match** —
    `digital-frames-card.js:298`: checks
    `reg.platform === 'fraimic'`, but entities are registered under the
    integration's actual domain, `digital_frames` — `'fraimic'` only ever
    appears as a storage-key migration constant, never an entity-registry
    platform value, so this auto-detection path for "+ Add Card" never
    fires.
40. **Card JS — crop-save doesn't guard a missing `battery_entity_id`** —
    `_cropSaveSend()` (~1491-1521) lacks the check `_send()` has
    (~1240-1243); in the narrow window before a frame's send-entity is
    registered, this can POST the literal string `"undefined"` as
    `entity_id`.

---

## Low / Style

- `DigitalFramesChargingSensor` is still a plain `SensorEntity` returning
  string `"True"`/`"False"` instead of `BinarySensorEntity`
  (`sensor.py:226-251`) — unfixed since the *original* v0.1.6 review, now
  three reviews open.
- `scripts/verify_packing.py:36` still points at
  `custom_components/fraimic` — broken since the domain rename to
  `digital_frames`; the project's own cited manual byte-identity safety net
  for the riskiest code path in the codebase currently cannot run at all.
- `const.py:10` `DEFAULT_PORT` still unused repo-wide — unfixed since v0.1.6.
- `image_converter.py:105` — `assert` used for a production sanity check,
  disabled under `python -O` — unfixed since v0.1.6.
- `image_converter.py:461-465` — bare `except Exception: pass` around EXIF
  handling swallows real bugs, not just "no EXIF" — unfixed since v0.1.6.
- `image_converter.py` — the documented `.bin` length formula
  `(width*height)//2` is wrong for any odd width in both byte layouts
  (confirmed by direct packing); harmless today since every registered
  resolution has even width, but `unpack_spectra6_bin` would reject its own
  packer's legitimate output the moment an odd-width panel is registered.
- `image_converter.py`'s `_open_as_rgb` composites transparency for
  `RGBA`/`LA` but not palette-mode (`"P"`) images with an `info["transparency"]`
  key — "transparent" GIF/indexed-PNG pixels come out as whatever raw color
  sits at that palette index, not white as the docstring claims.
- `image_converter.py`'s `_process_cropped` skips its aspect-ratio
  correction for a degenerate/reversed crop box (`w <= 0` or `h <= 0`),
  letting a subsequent unconditional resize stretch/smear the image with no
  error.
- `image_converter.py:242-243` — inline comment describing the rotation
  direction is backwards relative to the (correct) code and the function's
  own docstring — a landmine for a future "fix."
- `panel_codec.py`'s `encode_for_panel(codec_id=...)` doesn't actually use
  `codec_id` to select the Spectra byte layout for non-JPEG/PNG codecs — it
  re-derives layout from resolution via `frame_type_for_resolution`
  internally. Currently safe only because `_validate_registry()` enforces
  "same resolution ⇒ same codec" as a hard invariant; a future
  same-resolution/different-Spectra-codec panel would silently ignore the
  caller's explicit choice.
- `frame_types.py`'s `frame_type_for_resolution` is "first match wins" for
  colliding resolutions (13.3" and 13.1" both register 1200×1600) —
  currently harmless since both share layout and default timeout, but wrong
  if a future clone at a shared resolution needs a different profile.
- `helpers.py`'s `get_local_ip()` fallback subnet is a hardcoded
  `192.168.1.1` regardless of the host's actual network — silent/surprising
  if it ever triggers (containerized/IPv6-only HA hosts).
- `const.py`'s scene-pack catalog index is fetched from an unpinned `main`
  branch, unlike the xOTD/agenda renderer scripts, which are deliberately
  pinned to a commit SHA specifically to avoid an uncoordinated breaking
  change reaching every install — a documented, conscious tradeoff, but the
  weaker link in an otherwise careful pinning policy.
- `__init__.py:15` — unused `Platform` import.
- `__init__.py:518` — `hass.data[DOMAIN].pop(entry.entry_id)` with no
  default; not currently reachable, but one `.pop(..., None)` away from being
  defensive against a future partial-setup teardown path.
- Samsung MDC TLS fully disables certificate/hostname validation
  (`samsung.py:111-113`) — expected given a self-signed device cert with no
  pinning story, but worth calling out explicitly: an on-path LAN attacker
  could intercept/tamper with the session, including the PIN sent
  immediately after connect.
- Samsung MDC banner/auth read is a single `recv(64)` with no loop
  (`samsung.py:~120-133`) — could spuriously report "auth failed" on a
  TCP-fragmented response; this driver is explicitly untested on real
  hardware per the project's own docs.
- Panel JS: one `<option value="${f.entryId}">` (~line 9153) doesn't wrap
  `entryId` in `_esc()` unlike every other instance in the file — currently
  benign (HA-generated ids), but an inconsistency in an otherwise
  disciplined escaping pattern.
- Panel JS: crop editor's Save/Send buttons aren't disabled during the image
  load window right after `_openEditor` opens — clicking immediately can
  submit `{width: 0, height: 0, crop_box: null}`.
- Panel/Card JS version breadcrumbs (`PANEL_VERSION`, `CARD_VERSION`) remain
  inconsistent with `manifest.json`'s real version. The panel's is now
  intentionally a separate, documented "build breadcrumb" (bumped almost
  every commit) but nothing in the UI clarifies that it isn't the
  integration version; the card's (`0.5.0`) is still just stale.
- `library.py`'s Dropbox `list_folder` bin-cleanup on delete doesn't handle
  pagination (`has_more`/`cursor`) — orphaned `.bin` files on a
  large-enough cache go undeleted.

---

## Positive Notes

- `frame_types._validate_registry()` still fails loudly at import time if
  two panel types share a resolution with different byte layouts — the
  single best defense against this codebase's own worst-case failure class,
  and it hasn't regressed.
- The self-update zip extractor has a real, correct path-traversal guard
  before writing any extracted file (`update.py:726-728`) — good even though
  the missing-rollback gap (#3) undermines the happy path.
- `coordinator.py`'s `_async_update_data` three-tier exception handling
  (connection/timeout → response-status → generic fallback) is exactly
  right and should be the template for the send path (#9) and for Meural's
  orientation-follow/select-entity error handling (#26).
- The `token`-based `_clear_pending_if_current` pattern for queued sends is
  a genuinely well-thought-out guard against a slow in-flight send
  clobbering a newer one — it just isn't applied consistently everywhere the
  same race shape exists (#28, #29).
- Target-deleted degradation for scenes/skills feeding schedules
  (`STATUS_TARGET_MISSING`, disarm-not-retry-forever) is careful and
  correct in both the proactive (deletion-time) and reactive (fire-time)
  paths — the one gap is the different failure shape for unparsable
  triggers (#34).
- Concurrent skill renders are correctly isolated via a fresh per-render
  `run_dir`, and subprocess timeout handling correctly reaps the process
  (`kill()` + `communicate()`) rather than leaking zombies.
- Month-end schedule clamping and weekday-convention reconciliation between
  the Python backend and the JS frontend are both verified correct,
  including short-month edge cases.
- The Google Drive library backend's manifest-first, opaque-file-id design
  is immune to the path-traversal class in #2 by construction — it's the
  right template for fixing Local/Dropbox.
- `_safe_media_join` and `_safe_filename` remain correct and well-commented
  everywhere they're actually applied; the gap is specifically that the same
  discipline was never extended to `image_id` (#2) or the unprefixed
  `send_image` fallthrough (#7).
- Panel JS's thumbnail cache (`_loadThumbnail`/`_fetchThumb`/`_evictThumb`)
  and its wall-collision/grid-alignment math are both clean, careful, and
  bug-free in this pass despite being the most heavily reused code in the
  file.
- Card JS: object-URL revocation is correct at every `createObjectURL` site
  in the file, and the wall/library staleness-token pattern the panel is
  still missing in two places (#14, #15) is already correctly applied
  throughout the card.
- No shell/argv injection risk anywhere in the Live skills subprocess path
  — always `asyncio.create_subprocess_exec` (never a shell), and every
  path component that reaches the subprocess is internally generated
  (`uuid4`), never raw user input.
