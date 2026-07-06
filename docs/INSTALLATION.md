# Installation & Setup

## Install via HACS (recommended)

1. In Home Assistant, go to **Settings → Integrations → HACS**
2. Click the three-dot menu → **Custom repositories**
3. Paste `https://github.com/dsackr/fraimic-homeassistant` and set category to **Integration**
4. Click **Add**, then find **Fraimic** in HACS and install it
5. Restart Home Assistant

## Install manually

Copy the `custom_components/fraimic/` directory into your Home Assistant config folder under `custom_components/`.

```
config/
└── custom_components/
    └── fraimic/
```

Restart Home Assistant.

## Add your frames

Frames must be awake to be discovered — tap the frame to wake it if needed.

1. Go to **Settings → Integrations → Add Integration**
2. Search for **Fraimic**
3. Follow the prompts; discovered frames will appear automatically

If auto-discovery doesn't find a frame, you can enter its IP address manually from the same dialog.

## Requirements

- Fraimic frames (or a supported community clone — see below) on the same WiFi network as Home Assistant
- Home Assistant 2024.1 or newer
- [Pillow](https://pillow.readthedocs.io/) Python library (installed automatically)

## Supported hardware

Official Fraimic panels:

- Fraimic Canvas 13.3"
- Fraimic Canvas 31.5"

Community clone builds:

- 13.1" (Raspberry Pi Zero)
- 7.3" (ESP32-C6)

## Image format notes

Images are converted to Spectra 6 raw `.bin` format before being sent to frames. The conversion pipeline is based on the [Fraimic bin converter](https://github.com/Fraimic/fraimic_bin_converter) reference implementation. See also the [REST API guide](https://github.com/Fraimic/Fraimic_eink_canvas_home_assistant_restAPI_guide) for documentation on the endpoints this integration uses. E-ink panels can vary — test with your frame and [open an issue](https://github.com/dsackr/fraimic-homeassistant/issues) if the display looks wrong.

## Issues & support

[https://github.com/dsackr/fraimic-homeassistant/issues](https://github.com/dsackr/fraimic-homeassistant/issues)
