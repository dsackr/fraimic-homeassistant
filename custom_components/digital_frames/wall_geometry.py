"""Wall canvas geometry: compute a shared banner canvas and each member
frame's exact crop slice out of it, for a "message" split across a wall.

v1 is deliberately scoped to a single row or column of same-resolution
frames -- text is seam-sensitive in a way photos aren't, and an uneven/2D
wall layout gives the message renderer no way to know where a bezel gap
falls. Restricting to a uniform line keeps every seam at an exact i/N
fraction, so no scale-factor math or center-of-mass guessing is needed; a
layout this repo can't render safely is rejected with a clear error
instead of producing a silently ugly banner.

walls.Wall.placements supplies each member frame's *position* only -- its
*size* is resolved fresh via helpers.render_spec_for_hass_entry, not
walls.tile_dims (a static, preview-canvas-only snapshot that can disagree
with a follow-device frame's live gsensor orientation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry  # noqa: F401
    from homeassistant.core import HomeAssistant

    from .walls import Wall

# Placement coordinates come from the panel's drag UI (walls.py's _GRID =
# 20 snap) -- a few pixels of jitter between frames meant to share a row or
# column is normal drag imprecision, not a layout mistake.
_COLINEAR_TOLERANCE = 30.0


class WallGeometryError(Exception):
    """Raised when a wall's member frames can't be composed into one shared
    banner canvas -- mismatched resolutions, frames not placed on the wall,
    or not arranged in a single row/column."""


@dataclass(frozen=True)
class WallCanvasGeometry:
    """One shared banner canvas size, and each member frame's fractional
    crop box (x0, y0, x1, y1) into it -- ready to hand straight to
    panel_codec.encode_for_panel[_with_preview]'s crop_box param."""

    canvas_width: int
    canvas_height: int
    crop_boxes: dict[str, tuple[float, float, float, float]]


def compute_wall_canvas_geometry(
    hass: "HomeAssistant", wall: "Wall", member_entry_ids: list[str]
) -> WallCanvasGeometry:
    """Compute a shared banner canvas + per-frame crop slices for *wall*'s
    given member frames.

    Raises WallGeometryError if:
    - member_entry_ids is empty
    - any entry_id isn't placed on this wall, or its config entry is gone
    - member frames don't all share the same effective (width, height)
      (post orientation-lock -- see helpers.render_spec_for_hass_entry)
    - more than one frame is given and they aren't colinear (all sharing
      one x -> a column, or one y -> a row)
    """
    from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

    if not member_entry_ids:
        raise WallGeometryError("No frames given to compose a wall banner for")

    sizes: set[tuple[int, int]] = set()
    positions: dict[str, tuple[float, float]] = {}
    for entry_id in member_entry_ids:
        placement = wall.placements.get(entry_id)
        if placement is None:
            raise WallGeometryError(
                f"Frame '{entry_id}' is not placed on wall '{wall.wall_id}'"
            )
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise WallGeometryError(f"Frame '{entry_id}' is no longer configured")
        spec = render_spec_for_hass_entry(hass, entry)
        sizes.add((spec.width, spec.height))
        positions[entry_id] = (float(placement["x"]), float(placement["y"]))

    if len(sizes) > 1:
        raise WallGeometryError(
            "Wall banner messages require every target frame to share the "
            f"same resolution; got {sorted(sizes)}"
        )
    frame_w, frame_h = next(iter(sizes))

    xs = [pos[0] for pos in positions.values()]
    ys = [pos[1] for pos in positions.values()]
    is_row = (max(ys) - min(ys)) <= _COLINEAR_TOLERANCE
    is_column = (max(xs) - min(xs)) <= _COLINEAR_TOLERANCE
    if len(member_entry_ids) > 1 and not (is_row or is_column):
        raise WallGeometryError(
            "Wall banner messages require target frames arranged in a "
            "single row or column"
        )

    # A lone frame is trivially both a "row" and a "column" of one -- pick
    # row arbitrarily; it degenerates to the same (0,0,1,1) crop box either
    # way.
    axis = "row" if (is_row or len(member_entry_ids) == 1) else "column"
    if axis == "row":
        ordered = sorted(member_entry_ids, key=lambda eid: positions[eid][0])
    else:
        ordered = sorted(member_entry_ids, key=lambda eid: positions[eid][1])

    n = len(ordered)
    canvas_width = frame_w * n if axis == "row" else frame_w
    canvas_height = frame_h if axis == "row" else frame_h * n

    crop_boxes: dict[str, tuple[float, float, float, float]] = {}
    for i, entry_id in enumerate(ordered):
        if axis == "row":
            crop_boxes[entry_id] = (i / n, 0.0, (i + 1) / n, 1.0)
        else:
            crop_boxes[entry_id] = (0.0, i / n, 1.0, (i + 1) / n)

    return WallCanvasGeometry(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        crop_boxes=crop_boxes,
    )
