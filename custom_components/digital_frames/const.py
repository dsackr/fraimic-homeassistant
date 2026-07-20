"""Constants for the Digital Frames integration."""

from homeassistant.const import Platform

DOMAIN = "digital_frames"

# User-facing product name (HACS, sidebar, media browser, banners).
PRODUCT_NAME = "Digital Frames"

# Local library root under HA config/. New installs use LIBRARY_DIRNAME;
# first load renames LEGACY_LIBRARY_DIRNAME → LIBRARY_DIRNAME when present
# so albums/originals survive the product rename (see library.py).
LIBRARY_DIRNAME = "digital_frames_library"
LEGACY_LIBRARY_DIRNAME = "fraimic_library"
# Local thumbnail / bin cache roots (same one-shot rename pattern).
CACHE_DIRNAME = "digital_frames_cache"
LEGACY_CACHE_DIRNAME = "fraimic_cache"
ADDONS_DIRNAME = "digital_frames_addons"
LEGACY_ADDONS_DIRNAME = "fraimic_addons"

# Pre-rename domain — used only to migrate library settings store keys.
LEGACY_DOMAIN = "fraimic"

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
CONF_DRIVER = "driver"            # FramePort driver id (see DRIVER_*)

# FramePort driver ids (entry.data[CONF_DRIVER]). Default/absent = Fraimic
# local Spectra HTTP family (official + API-compatible clones).
DRIVER_FRAIMIC = "fraimic"
DRIVER_MEURAL = "meural"
DRIVER_SAMSUNG = "samsung"  # Samsung EM32DX e-paper (experimental; MDC)

# Meural Canvas common native resolution (landscape). User can override
# in the Meural config flow when a panel reports differently.
MEURAL_DEFAULT_WIDTH = 1920
MEURAL_DEFAULT_HEIGHT = 1080
MEURAL_SIZE_LABEL = "meural"

# Samsung EM32DX (Joyous / fayep protocol notes). Landscape native.
SAMSUNG_DEFAULT_WIDTH = 2560
SAMSUNG_DEFAULT_HEIGHT = 1440
SAMSUNG_SIZE_LABEL = "samsung"
SAMSUNG_MDC_PORT = 1515
CONF_MDC_PIN = "mdc_pin"
DEFAULT_MDC_PIN = "000000"

# Frame display modes
MODE_MANUAL = "manual"
MODE_AGENDA = "agenda"
MODE_ROTATION = "rotation"

# Frame types (physical size, resolution, byte layout, official-vs-clone
# origin) live in frame_types.py's FRAME_TYPES registry, not here.
# Meural is NOT a FRAME_TYPES row — it is a separate driver (DRIVER_MEURAL).

# HA platforms this integration provides
# LIGHT is Meural-only (backlight); Fraimic e-ink entries no-op in light.py.
PLATFORMS = [Platform.SENSOR, Platform.SELECT, Platform.CAMERA, Platform.LIGHT]

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

# Dispatcher signal fired whenever a scheduled event is created, edited,
# deleted, fires, or breaks (target_missing). No entity platform listens
# today -- schedules are panel-local state like walls.
SIGNAL_SCHEDULES_UPDATED = f"{DOMAIN}_schedules_updated"

# Dispatcher signal fired whenever a skill (frame-agnostic generated
# content preset, e.g. Word of the Day) is created, edited, or deleted.
SIGNAL_SKILLS_UPDATED = f"{DOMAIN}_skills_updated"

# Where scene pack content (manifest + source images) is fetched from at
# install time. Content lives in a separate repository (dsackr/frame-addons)
# under scene_packs/ so the integration stays lightweight. Deliberately
# tracks `main` (not pinned) -- new art packs and image fixes should show up without a
# ha-digital-frames release.
SCENE_PACK_RAW_BASE = (
    "https://raw.githubusercontent.com/dsackr/frame-addons/main"
)
SCENE_PACK_INDEX_URL = f"{SCENE_PACK_RAW_BASE}/scene_packs/index.json"

# Gallery catalog schema_version supported by this integration build
# (Content Platform Phase 7). Higher catalog schema_versions are ignored
# with a log warning until we add a new decoder.
GALLERY_CATALOG_SCHEMA_VERSION = 1

# The xOTD renderer script skills.py downloads and runs as a subprocess for
# every text-mode skill render (see skills.py's _async_script_bytes). Unlike
# SCENE_PACK_RAW_BASE above, this is pinned to a specific frame-addons
# commit rather than tracking `main`: skills.py depends on that commit's
# exact CLI contract (--render-only, --config <path>, writing xotd.bin next
# to it) for its per-render subprocess isolation -- an unrelated frame-addons
# change to main that altered or dropped those flags would otherwise break
# every skill render for every installed user, with no coordinated rollout.
# Bump this deliberately (to a new commit SHA or tag) only when a
# frame-addons change adds a capability skills.py needs to start relying on.
XOTD_RENDERER_PINNED_BASE = (
    "https://raw.githubusercontent.com/dsackr/frame-addons/"
    "a9fa048b7aab3b6661bd1cf37bd94949b0e23f77"
)
XOTD_RENDERER_SCRIPT_PATH = "addons/xotd/xotd_renderer.py"

# Daily Agenda Live skill renderer (Content Platform Phase 4). Same pin
# policy as xOTD: bump only when the CLI contract changes.
AGENDA_RENDERER_PINNED_BASE = (
    "https://raw.githubusercontent.com/dsackr/frame-addons/"
    "345294b8589124039210f3957357feb4a0b3e35a"
)
AGENDA_RENDERER_SCRIPT_PATH = "addons/daily_agenda/agenda_renderer.py"

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
# Meural: when True (default), coordinator copies gsensor portrait/landscape
# into CONF_ORIENTATION so crop/send match the physical hang. Manual lock
# via the Orientation select clears this flag.
CONF_ORIENTATION_FOLLOW_DEVICE = "orientation_follow_device"
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

