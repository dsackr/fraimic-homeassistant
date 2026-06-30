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
CONF_MODE = "mode"

# Frame display modes
MODE_MANUAL = "manual"
MODE_AGENDA = "agenda"
MODE_ROTATION = "rotation"

# Frame resolutions: name → (width_px, height_px), keyed to match the
# physical panel sizes Fraimic itself uses ("13.3" / "31.5"). Verified
# against E Ink's EL133UF1 (13.3", portrait-native) and the 31.5" Spectra 6
# panel spec sheet (landscape-native) -- these are real hardware pixel
# counts, not placeholders.
FRAME_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "13.3": (1200, 1600),
    "31.5": (2560, 1440),
}

# HA platforms this integration provides
PLATFORMS = [Platform.SENSOR]
