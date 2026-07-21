"""Wall canvas geometry: compute a shared banner canvas + per-frame crop
slices for a wall-banner message (KPF: compose & send a styled message).

If this silently breaks: a wall banner's frames could show non-adjacent or
misaligned slices, or a stale/live orientation disagreement could shift a
follow-device frame's crop after it physically flips.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.const import (
    CONF_DRIVER,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DOMAIN,
    DRIVER_MEURAL,
)
from custom_components.digital_frames.wall_geometry import (
    WallGeometryError,
    compute_wall_canvas_geometry,
)
from custom_components.digital_frames.walls import Wall


def _wall(placements: dict) -> Wall:
    return Wall(wall_id="wall-1", name="Test Wall", placements=placements)


async def test_single_frame_degenerates_to_full_crop(hass, make_frame_entry):
    entry = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({"entry-0": {"x": 100.0, "y": 100.0}})

    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0"])

    assert geometry.canvas_width == 1200
    assert geometry.canvas_height == 1600
    assert geometry.crop_boxes["entry-0"] == (0.0, 0.0, 1.0, 1.0)


async def test_row_of_frames_sorted_left_to_right(hass, make_frame_entry):
    entries = []
    for i, x in enumerate((300.0, 100.0, 200.0)):  # deliberately out of order
        entry = make_frame_entry(entry_id=f"entry-{i}", width=1200, height=1600)
        entry.add_to_hass(hass)
        entries.append((entry, x))
    placements = {entry.entry_id: {"x": x, "y": 50.0} for entry, x in entries}
    wall = _wall(placements)

    geometry = compute_wall_canvas_geometry(
        hass, wall, [e.entry_id for e, _ in entries]
    )

    assert geometry.canvas_width == 1200 * 3
    assert geometry.canvas_height == 1600
    # entries[1] has x=100 (leftmost) -> slice 0; entries[2] x=200 -> slice 1;
    # entries[0] x=300 -> slice 2.
    assert geometry.crop_boxes[entries[1][0].entry_id] == (0 / 3, 0.0, 1 / 3, 1.0)
    assert geometry.crop_boxes[entries[2][0].entry_id] == (1 / 3, 0.0, 2 / 3, 1.0)
    assert geometry.crop_boxes[entries[0][0].entry_id] == (2 / 3, 0.0, 1.0, 1.0)


async def test_column_of_frames_sorted_top_to_bottom(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=1200, height=1600)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 50.0, "y": 200.0},
            "entry-1": {"x": 50.0, "y": 50.0},
        }
    )

    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])

    assert geometry.canvas_width == 1200
    assert geometry.canvas_height == 1600 * 2
    assert geometry.crop_boxes["entry-1"] == (0.0, 0.0, 1.0, 0.5)  # y=50, topmost
    assert geometry.crop_boxes["entry-0"] == (0.0, 0.5, 1.0, 1.0)  # y=200


async def test_mismatched_resolution_rejected(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=800, height=480)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 0.0, "y": 0.0},
            "entry-1": {"x": 1200.0, "y": 0.0},
        }
    )

    with pytest.raises(WallGeometryError, match="same resolution"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])


async def test_non_colinear_placements_rejected(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=1200, height=1600)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 0.0, "y": 0.0},
            "entry-1": {"x": 200.0, "y": 200.0},
        }
    )

    with pytest.raises(WallGeometryError, match="row or column"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])


async def test_frame_not_placed_on_wall_rejected(hass, make_frame_entry):
    entry = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({})

    with pytest.raises(WallGeometryError, match="not placed"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0"])


async def test_empty_member_list_rejected(hass):
    wall = _wall({})
    with pytest.raises(WallGeometryError, match="No frames"):
        compute_wall_canvas_geometry(hass, wall, [])


async def test_missing_config_entry_rejected(hass):
    wall = _wall({"gone-entry": {"x": 0.0, "y": 0.0}})
    with pytest.raises(WallGeometryError, match="no longer configured"):
        compute_wall_canvas_geometry(hass, wall, ["gone-entry"])


async def test_live_follow_device_orientation_wins_over_stale_option(
    hass, make_frame_entry
):
    """A Meural frame with follow-device on and a stale stored orientation
    option must use its live gsensor reading for sizing, not walls.
    tile_dims-style static data -- otherwise a frame that's physically
    flipped since the wall was last saved gets a crop computed against the
    wrong aspect ratio."""
    entry = make_frame_entry(
        entry_id="entry-0",
        width=1200,
        height=1600,
        options={
            CONF_ORIENTATION_FOLLOW_DEVICE: True,
        },
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DRIVER: DRIVER_MEURAL}
    )

    class _FakeCoordinator:
        data = {"device_orientation": "landscape"}

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _FakeCoordinator()

    wall = _wall({"entry-0": {"x": 0.0, "y": 0.0}})
    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0"])

    # Locked landscape on a native-portrait (1200x1600) buffer swaps the
    # effective composition size to 1600x1200.
    assert geometry.canvas_width == 1600
    assert geometry.canvas_height == 1200
