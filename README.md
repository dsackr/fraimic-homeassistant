# Fraimic for Home Assistant

Turn your Fraimic e-ink frames into a photo wall that Home Assistant actually controls — no app, no cloud, no account. Point it at your frames and start sending photos in minutes.

## Why you'll want this

- **No cloud in the loop.** Everything talks to your frames over your own WiFi. No account to create, no vendor server between you and your photos.
- **One tap turns a wall into a scene.** Match photos to frames — say, four frames each showing a different shot — and flip the whole wall at once from a dashboard, a voice command, or an automation.
- **Your library, not a photo dump.** Upload once, organize into albums, reuse the same photo across frames and scenes without duplicating files.
- **A gallery wall out of the box.** Install a curated public-domain art pack (Monet, da Vinci, van Gogh, and more) with one click — Home Assistant imports it, matches pieces to your frames by orientation, and builds a ready-to-send scene automatically.
- **Set it and forget it.** Daily agenda mode turns your calendar into a frame display; rotation mode cycles albums from Google Photos or iCloud. Once configured, it just runs.
- **Works with the community, not just Fraimic hardware.** Built-in support for popular community clone builds alongside official Fraimic panels.

## Quick start

1. Install through HACS: add `https://github.com/dsackr/fraimic-homeassistant` as a custom repository (category: Integration), then install **Fraimic**.
2. Restart Home Assistant.
3. Go to **Settings → Integrations → Add Integration**, search **Fraimic**, and follow the prompts. Wake your frame first so it's discoverable.

That's it — your frame shows up as a device, ready to receive photos.

Manual install, troubleshooting, and full hardware requirements: see [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Credits

**Meural Canvas local protocol** — endpoint inventory for the on-device
`/remote/` HTTP API (identify, system check, backlight, suspend/resume,
postcard upload, galleries JSON, etc.) was published by **Guy Sie** in
[HA-meural](https://github.com/GuySie/ha-meural) (MIT License,
Copyright © 2020 Guy Sie). Our Meural support is a **local-only** FramePort
driver inspired by that documentation; we do not use Meural cloud/Cognito and
do not vendor HA-meural code. If you want full Meural cloud playlists and
media-player UX in Home Assistant, use HA-meural.

**Samsung EM32DX (experimental)** — MDC content-download packet layout, TLS
PIN auth, and WoL/SSDP workflow are documented in
[fayep/Joyous](https://github.com/fayep/Joyous) (`Samsung/samsung_serve.py`
and hub MDC code). Our driver is an independent HA reimplementation; it has
**not been validated on real Samsung hardware** in this project. InkJoy is
**not** integrated here (vendor control plane is MQTT — deferred).

## License

MIT — see [LICENSE](LICENSE).

## Get involved

- ⭐ Star the repo if this is useful to you
- 🐛 [Report an issue](https://github.com/dsackr/fraimic-homeassistant/issues) if a frame misbehaves
- 🤝 Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)

## How this project tests itself

See [docs/KEY_PRODUCT_FLOWS.md](docs/KEY_PRODUCT_FLOWS.md) for the catalog
of what the integration does and how each flow is tested, and
[TESTING_STRATEGY.md](TESTING_STRATEGY.md) for the overall testing
strategy and coverage roadmap.
