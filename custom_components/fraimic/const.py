"""Constants for the Fraimic integration."""

from homeassistant.const import Platform

DOMAIN = "fraimic"

# Polling interval in seconds (5 minutes default)
DEFAULT_SCAN_INTERVAL = 300

DEFAULT_PORT = 80

# API endpoints
API_INFO = "/api/info"
API_RESTART = "/api/restart"
API_SLEEP = "/api/sleep"
API_REFRESH = "/api/refresh"
API_IMAGE = "/api/image"

# Config entry keys
CONF_HOST = "host"
CONF_NAME = "name"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_DEVICE_KEY = "device_key"  # persistent Fraimic device identifier
CONF_MAC = "mac_address"         # WiFi MAC (normalised, no colons)
CONF_MODE = "mode"
CONF_SIZE = "size"                # diagonal panel size label, e.g. "13.3"

# Frame display modes
MODE_MANUAL = "manual"
MODE_AGENDA = "agenda"
MODE_ROTATION = "rotation"

# Frame types (physical size, resolution, byte layout, official-vs-clone
# origin) live in frame_types.py's FRAME_TYPES registry, not here.

# HA platforms this integration provides
PLATFORMS = [Platform.SENSOR, Platform.SELECT]

# The "kind" marker (entry.data["kind"]) for the auto-created, device-less
# config entry that hosts scene entities -- see scenes.py / scene.py for why
# scenes can't just live on a frame's own config entry.
KIND_SCENES_HUB = "scenes_hub"
HUB_PLATFORMS = [Platform.SCENE]

# Dispatcher signal fired whenever a scene is created, edited, or deleted so
# the scene entity platform can add/remove/rename entities without a reload.
SIGNAL_SCENES_UPDATED = f"{DOMAIN}_scenes_updated"

# Dispatcher signal fired whenever a wall layout is created, edited, or
# deleted. No entity platform listens today -- walls are pure panel-local
# state -- but this mirrors SIGNAL_SCENES_UPDATED for consistency.
SIGNAL_WALLS_UPDATED = f"{DOMAIN}_walls_updated"

# Where scene pack content (manifest + source images) is fetched from at
# install time. Content lives in this same repo under scene_packs/ rather
# than a separate service, so installing a pack is just downloading public
# files -- no server-side component to run or keep available.
SCENE_PACK_RAW_BASE = (
    "https://raw.githubusercontent.com/dsackr/fraimic-homeassistant/main"
)
SCENE_PACK_INDEX_URL = f"{SCENE_PACK_RAW_BASE}/scene_packs/index.json"

# Orientation config options.
#
# CONF_ORIENTATION is a render-time preference stored in entry.options (the
# per-frame Orientation select entity writes it; see select.py). It never
# touches entry.data's width/height -- those always stay the panel's native
# (frame-reported) dimensions. "auto" is the Fraimic way: any picture goes to
# any frame, mismatched-orientation images are displayed sideways at full
# size. "portrait"/"landscape" lock the frame: mismatched images are
# auto-cropped (centered cover) to stay upright instead.
CONF_ORIENTATION = "orientation"
ORIENTATION_AUTO = "auto"
ORIENTATION_PORTRAIT = "portrait"
ORIENTATION_LANDSCAPE = "landscape"
CONF_ROTATE_PORTRAIT_180 = "rotate_portrait_180"
CONF_ROTATE_LANDSCAPE_180 = "rotate_landscape_180"

# Which edge of the panel points up when the frame is physically hung in its
# non-native orientation (e.g. a portrait-native 13.3" hung landscape).
# Official Fraimic frames are built to hang one specific way ("left edge
# up"); clones can be mounted either way, so this is configurable per frame
# (integration options) with the Fraimic behaviour as the default.
CONF_ROTATION_EDGE = "rotation_edge"
EDGE_LEFT = "left"    # Fraimic default
EDGE_RIGHT = "right"
