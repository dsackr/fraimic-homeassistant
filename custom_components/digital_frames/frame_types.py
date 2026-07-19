"""Registry of every frame type the integration knows how to drive.

A "frame type" is identified by the same label stored in a config entry's
CONF_SIZE (e.g. "13.3") and declares everything about that physical panel
that isn't derivable from its pixel resolution alone:

- which **PanelCodec** packs pixels for the wire (see panel_codec.py /
  image_converter.py) — e.g. Spectra 6 split-half vs sequential
- transport hints such as image-upload timeout (ESP32 redraws block long)
- whether it's an official Fraimic panel or a community build

This registry exists so that adding support for a new panel is an explicit,
validated registration -- not a resolution tuple silently dropped into a
frozenset and hoped to never collide with another panel's requirements.

See docs/FRAME_PORT.md: core vs driver/transport vs codec layers. The 7.3"
panel is not "identical clone bytes" of official Fraimic — it shares a
local Spectra HTTP transport family but uses a different codec
(spectra6_sequential) and needs a long send timeout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

# Byte layouts a panel's .bin format can use -- see image_converter.py's
# module docstring for what these mean on the wire.
LAYOUT_SPLIT_HALF = "split_half"
LAYOUT_SEQUENTIAL = "sequential"

# Stable codec ids (cache keys / FramePort preferred_payload family).
# These name *how* pixels become wire bytes — not marketing origin.
CODEC_SPECTRA6_SPLIT_HALF = "spectra6_split_half"
CODEC_SPECTRA6_SEQUENTIAL = "spectra6_sequential"

_LAYOUT_TO_CODEC: dict[str, str] = {
    LAYOUT_SPLIT_HALF: CODEC_SPECTRA6_SPLIT_HALF,
    LAYOUT_SEQUENTIAL: CODEC_SPECTRA6_SEQUENTIAL,
}

ORIGIN_OFFICIAL = "official"
ORIGIN_CLONE = "clone"

# Default image-upload HTTP timeout (seconds). ESP32 sequential panels need
# this headroom because they accept the body then block the response on the
# e-ink redraw; official panels keep the same budget so behaviour stays
# uniform unless a profile overrides it.
DEFAULT_SEND_TIMEOUT_S = 240


@dataclass(frozen=True)
class FrameType:
    """One registered panel type (local Spectra HTTP driver family)."""

    id: str  # matches CONF_SIZE, e.g. "13.3"
    display_name: str
    resolution: tuple[int, int]
    byte_layout: str  # LAYOUT_SPLIT_HALF | LAYOUT_SEQUENTIAL
    origin: str  # ORIGIN_OFFICIAL | ORIGIN_CLONE
    platform: str | None = None  # e.g. "Raspberry Pi Zero", "ESP32-C6"
    send_timeout_s: int = DEFAULT_SEND_TIMEOUT_S

    @property
    def codec_id(self) -> str:
        """Stable id for the PanelCodec that packs this panel's payload."""
        try:
            return _LAYOUT_TO_CODEC[self.byte_layout]
        except KeyError as err:
            raise ValueError(
                f"Frame type '{self.id}' has unknown byte_layout "
                f"{self.byte_layout!r}"
            ) from err


# Verified against E Ink's EL133UF1 (13.3", portrait-native) and the 31.5"
# Spectra 6 panel spec sheet (landscape-native) for the official panels --
# these are real hardware pixel counts, not placeholders. Community entries
# include API-compatible builds; the 7.3" uses sequential packing (Waveshare
# E6 / epd7in3e-style), not Fraimic split-half — same transport family,
# different codec (see docs/FRAME_PORT.md §1.1).
FRAME_TYPES: dict[str, FrameType] = {
    "13.3": FrameType(
        id="13.3",
        display_name='Fraimic Canvas 13.3"',
        resolution=(1200, 1600),
        byte_layout=LAYOUT_SPLIT_HALF,
        origin=ORIGIN_OFFICIAL,
    ),
    "31.5": FrameType(
        id="31.5",
        display_name='Fraimic Canvas 31.5"',
        resolution=(2560, 1440),
        byte_layout=LAYOUT_SPLIT_HALF,
        origin=ORIGIN_OFFICIAL,
    ),
    "13.1": FrameType(
        id="13.1",
        display_name='13.1" Community Clone',
        resolution=(1200, 1600),
        byte_layout=LAYOUT_SPLIT_HALF,
        origin=ORIGIN_CLONE,
        platform="Raspberry Pi Zero",
    ),
    "7.3": FrameType(
        id="7.3",
        display_name='7.3" Community Panel (ESP32-C6)',
        resolution=(800, 480),
        byte_layout=LAYOUT_SEQUENTIAL,
        origin=ORIGIN_CLONE,
        platform="ESP32-C6",
        # Redraw blocks the HTTP response; see coordinator.async_send_image.
        send_timeout_s=DEFAULT_SEND_TIMEOUT_S,
    ),
}


def _validate_registry() -> None:
    """Two frame types sharing a resolution must agree on codec (byte layout)
    -- the .bin cache is keyed by resolution, not frame type id / codec_id,
    so a mismatch here would silently serve the wrong bytes to one of them.
    Fail loudly at import time instead. Phase 2 may key the cache on
    codec_id; until then this invariant stays hard."""
    seen: dict[tuple[int, int], FrameType] = {}
    for frame_type in FRAME_TYPES.values():
        # Force codec_id validation at import.
        _ = frame_type.codec_id
        prior = seen.get(frame_type.resolution)
        if prior is not None and prior.byte_layout != frame_type.byte_layout:
            raise ValueError(
                f"Frame types '{prior.id}' and '{frame_type.id}' share "
                f"resolution {frame_type.resolution} but declare different "
                f"codecs ('{prior.codec_id}' vs '{frame_type.codec_id}'). "
                f"The .bin cache can't distinguish them at that resolution "
                f"-- give one of them a distinct resolution, or extend the "
                f"cache key to include codec_id."
            )
        seen[frame_type.resolution] = frame_type


_validate_registry()


def frame_type_for_resolution(width: int, height: int) -> FrameType:
    """Return the registered FrameType for (width, height).

    Orientation-agnostic: (height, width) matches too. Some frames report
    swapped dimensions from /api/info after being physically rotated, and the
    coordinator persists whatever the frame reports -- the physical panel
    (and its codec) is the same either way.

    When two types share a resolution they agree on codec (see
    _validate_registry); the first match is returned.
    """
    for frame_type in FRAME_TYPES.values():
        if frame_type.resolution in ((width, height), (height, width)):
            return frame_type
    raise ValueError(
        f"No registered frame type has resolution {width}x{height}"
    )


def byte_layout_for_resolution(width: int, height: int) -> str:
    """Return the .bin byte layout registered for (width, height).

    Prefer codec_id_for_resolution / panel_codec when adding new call sites;
    this remains for packers and external scripts that speak layout names.
    """
    return frame_type_for_resolution(width, height).byte_layout


def codec_id_for_resolution(width: int, height: int) -> str:
    """Return the PanelCodec id for a panel at this resolution."""
    return frame_type_for_resolution(width, height).codec_id


def send_timeout_for_entry(entry: "ConfigEntry") -> int:
    """Image-upload timeout (seconds) for a config entry's panel profile.

    Prefers CONF_SIZE when present; falls back to stored width/height; then
    DEFAULT_SEND_TIMEOUT_S.
    """
    # Local import avoids a hard dependency cycle with const at module load
    # in odd import orders; CONF_SIZE is a plain string key.
    size = entry.data.get("size")
    if isinstance(size, str) and size in FRAME_TYPES:
        return FRAME_TYPES[size].send_timeout_s

    width = entry.data.get("width")
    height = entry.data.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        try:
            return frame_type_for_resolution(width, height).send_timeout_s
        except ValueError:
            pass
    return DEFAULT_SEND_TIMEOUT_S
