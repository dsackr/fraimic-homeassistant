# Fraimic for Home Assistant

Local Home Assistant integration for Fraimic e-ink canvas frames. Controls your frames directly over WiFi — no cloud, no account required.

## Features

- **Auto-discovery** — finds Fraimic frames on your local network automatically
- **Sensors** — battery level, WiFi signal strength, firmware version
- **Send any image** — push PNG or JPG files to a frame; images are auto-converted to Spectra 6 format on the fly
- **Controls** — refresh display, put frame to sleep, restart frame
- **Daily agenda mode** — pulls calendar events and renders them as an image for the frame
- **Shared photo library with albums** — upload one or many photos at once into a new or existing album; a photo can belong to multiple albums with no duplication, and albums show up as folders in the panel
- **Scenes** — pick an album and match its photos to frames (e.g. four frames on a wall each showing a different photo), then send the whole layout at once from the panel, via the `fraimic.send_scene` service, or by voice — every scene is also a native `scene.*` entity, so once exposed to your voice assistant, "Alexa, activate Countdown Wall" or "Hey Google, activate Countdown Wall" works out of the box
- **Scene packs** — install a curated, public-domain art collection (Monet, da Vinci, van Gogh, Classic Art) straight from the panel with one click; images are imported into your library and auto-matched to your frames by orientation, with a ready-to-send scene built automatically — no manual setup
- **Photo rotation mode** — cycles through albums from Google Photos or iCloud

## Installation

### Via HACS (recommended)

1. In Home Assistant, go to **Settings → Integrations → HACS**
2. Click the three-dot menu → **Custom repositories**
3. Paste `https://github.com/dsackr/fraimic-homeassistant` and set category to **Integration**
4. Click **Add**, then find **Fraimic** in HACS and install it
5. Restart Home Assistant

### Manual

Copy the `custom_components/fraimic/` directory into your Home Assistant config folder under `custom_components/`.

```
config/
└── custom_components/
    └── fraimic/
```

Restart Home Assistant.

## Setup

Frames must be awake to be discovered — tap the frame to wake it if needed.

1. Go to **Settings → Integrations → Add Integration**
2. Search for **Fraimic**
3. Follow the prompts; discovered frames will appear automatically

## Requirements

- Fraimic frames on the same WiFi network as Home Assistant
- Home Assistant 2024.1 or newer
- [Pillow](https://pillow.readthedocs.io/) Python library (installed automatically)

## Image Format Note

Images are converted to Spectra 6 raw `.bin` format before being sent to frames. This format is community-validated, but e-ink panels can vary — test with your frame and [open an issue](https://github.com/dsackr/fraimic-homeassistant/issues) if the display looks wrong.

## Issues & Support

[https://github.com/dsackr/fraimic-homeassistant/issues](https://github.com/dsackr/fraimic-homeassistant/issues)
