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
PLATFORMS = [Platform.SENSOR]

# The "kind" marker (entry.data["kind"]) for the auto-created, device-less
# config entry that hosts scene entities -- see scenes.py / scene.py for why
# scenes can't just live on a frame's own config entry.
KIND_SCENES_HUB = "scenes_hub"
HUB_PLATFORMS = [Platform.SCENE]

# Dispatcher signal fired whenever a scene is created, edited, or deleted so
# the scene entity platform can add/remove/rename entities without a reload.
SIGNAL_SCENES_UPDATED = f"{DOMAIN}_scenes_updated"

# Where scene pack content (manifest + source images) is fetched from at
# install time. Content lives in this same repo under scene_packs/ rather
# than a separate service, so installing a pack is just downloading public
# files -- no server-side component to run or keep available.
SCENE_PACK_RAW_BASE = (
    "https://raw.githubusercontent.com/dsackr/fraimic-homeassistant/main"
)
SCENE_PACK_INDEX_URL = f"{SCENE_PACK_RAW_BASE}/scene_packs/index.json"

# Orientation config options
CONF_ORIENTATION = "orientation"
ORIENTATION_AUTO = "auto"
ORIENTATION_PORTRAIT = "portrait"
ORIENTATION_LANDSCAPE = "landscape"
CONF_ROTATE_PORTRAIT_180 = "rotate_portrait_180"
CONF_ROTATE_LANDSCAPE_180 = "rotate_landscape_180"
