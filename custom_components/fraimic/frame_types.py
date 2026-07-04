"""Registry of every frame type the integration knows how to drive.

A "frame type" is identified by the same label stored in a config entry's
CONF_SIZE (e.g. "13.3") and declares everything about that physical panel
that isn't derivable from its pixel resolution alone: which byte layout its
.bin format needs (see image_converter.py) and whether it's an official
Fraimic panel or a community clone build.

This registry exists so that adding support for a new panel is an explicit,
validated registration -- not a resolution tuple silently dropped into a
frozenset and hoped to never collide with another panel's requirements.
"""

from __future__ import annotations

from dataclasses import dataclass

# Byte layouts a panel's .bin format can use -- see image_converter.py's
# module docstring for what these mean on the wire.
LAYOUT_SPLIT_HALF = "split_half"
LAYOUT_SEQUENTIAL = "sequential"

ORIGIN_OFFICIAL = "official"
ORIGIN_CLONE = "clone"


@dataclass(frozen=True)
class FrameType:
    """One registered panel type."""

    id: str  # matches CONF_SIZE, e.g. "13.3"
    display_name: str
    resolution: tuple[int, int]
    byte_layout: str  # LAYOUT_SPLIT_HALF | LAYOUT_SEQUENTIAL
    origin: str  # ORIGIN_OFFICIAL | ORIGIN_CLONE
    platform: str | None = None  # e.g. "Raspberry Pi Zero", "ESP32-C6"


# Verified against E Ink's EL133UF1 (13.3", portrait-native) and the 31.5"
# Spectra 6 panel spec sheet (landscape-native) for the official panels --
# these are real hardware pixel counts, not placeholders. The clone entries
# describe community reimplementations of the Fraimic API/firmware protocol
# on non-Fraimic hardware.
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
        display_name='7.3" Community Clone',
        resolution=(800, 480),
        byte_layout=LAYOUT_SEQUENTIAL,
        origin=ORIGIN_CLONE,
        platform="ESP32-C6",
    ),
}


def _validate_registry() -> None:
    """Two frame types sharing a resolution must agree on byte layout --
    the .bin cache is keyed by resolution, not frame type id, so a mismatch
    here would silently serve the wrong bytes to one of them. Fail loudly at
    import time instead."""
    seen: dict[tuple[int, int], FrameType] = {}
    for frame_type in FRAME_TYPES.values():
        prior = seen.get(frame_type.resolution)
        if prior is not None and prior.byte_layout != frame_type.byte_layout:
            raise ValueError(
                f"Frame types '{prior.id}' and '{frame_type.id}' share "
                f"resolution {frame_type.resolution} but declare different "
                f"byte layouts ('{prior.byte_layout}' vs "
                f"'{frame_type.byte_layout}'). The .bin cache can't "
                "distinguish them at that resolution -- give one of them a "
                "distinct resolution, or extend the cache key to include "
                "frame type id."
            )
        seen[frame_type.resolution] = frame_type


_validate_registry()


def byte_layout_for_resolution(width: int, height: int) -> str:
    """Return the .bin byte layout registered for (width, height).

    Safe to key purely on resolution because _validate_registry() guarantees
    every frame type sharing a resolution agrees on layout.

    Orientation-agnostic: (height, width) matches too. Some frames report
    swapped dimensions from /api/info after being physically rotated, and the
    coordinator persists whatever the frame reports -- the physical panel
    (and its byte layout) is the same either way.
    """
    for frame_type in FRAME_TYPES.values():
        if frame_type.resolution in ((width, height), (height, width)):
            return frame_type.byte_layout
    raise ValueError(
        f"No registered frame type has resolution {width}x{height}"
    )
