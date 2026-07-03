# Contributing to Fraimic for Home Assistant

Thanks for your interest in contributing. This is a custom HACS integration for Fraimic e-ink frames — it talks to the frame's local HTTP API and converts images to Spectra 6 binary format on the fly.

## How it works (the short version)

- **`coordinator.py`** — polls each frame's `/api/info` endpoint on a schedule; handles DHCP autodiscovery and IP self-healing
- **`library.py`** — pluggable image storage (local HA storage, Dropbox, Google Drive); stores a JSON manifest + original images; generates per-resolution `.bin` files on upload
- **`image_converter.py`** — converts any Pillow-readable image to Spectra 6 raw binary (4bpp, nibble-packed, left/right half split)
- **`fraimic-panel.js`** — vanilla JS custom panel; no frameworks; shadow DOM; talks to HA's REST/WS APIs with Bearer auth
- **`library_http.py`** — HTTP views registered with HA for the panel to call (image upload, crop save/clear, frame list, etc.)
- **`scenes.py`** — named (frame, image) assignment lists sendable all at once; local-only state (HA's `Store` helper), independent of the library's storage backend
- **`scenes_http.py`** — HTTP views for scene CRUD + send, mirroring `library_http.py`'s shape
- **`helpers.py`** — network utilities: `/api/info` probe, subnet scanner for IP self-healing

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

## Releasing (maintainers)

Releases are cut via `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."`. The GitHub Actions workflow tags the release; HACS picks it up automatically. Wait ~10 seconds after the release command before triggering a HACS download, as GitHub's zipball CDN takes a moment to generate.

## Pull requests

- Keep PRs focused — one feature or fix per PR
- Test on real hardware before submitting; internally-consistent code that doesn't work on the frame is not useful
- `fraimic-panel.js` is intentionally vanilla JS with no build step — keep it that way
- If you're changing the bin conversion format, include before/after photos of the frame output

## Issues

Open an issue if you're seeing incorrect colors, display artifacts, or API errors. Include your frame model and firmware version (visible in the integration's device page).
