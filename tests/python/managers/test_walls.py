"""Walls: virtual multi-frame layout, pure panel-local state (KPF 19).

If this silently breaks: removed/re-added frames haunt old layouts, or the
default wall stops tracking newly-added frames.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.walls import (
    DEFAULT_WALL_ID,
    DEFAULT_WALL_NAME,
    KIND_DEFAULT,
    WallError,
    WallManager,
)


@pytest.fixture
def wall_manager(hass):
    return WallManager(hass)


# ---------------------------------------------------------------------------
# Custom wall CRUD
# ---------------------------------------------------------------------------


async def test_create_custom_wall(wall_manager):
    result = await wall_manager.async_save_wall(
        "Living Room", {"entry-1": {"x": 10, "y": 20}}
    )
    assert result["name"] == "Living Room"
    assert result["placements"] == {"entry-1": {"x": 10.0, "y": 20.0}}


async def test_update_custom_wall(wall_manager):
    created = await wall_manager.async_save_wall("Original", {})
    updated = await wall_manager.async_save_wall(
        "Renamed", {"entry-1": {"x": 5, "y": 5}}, wall_id=created["wall_id"]
    )
    assert updated["wall_id"] == created["wall_id"]
    assert updated["name"] == "Renamed"


async def test_delete_custom_wall(wall_manager):
    created = await wall_manager.async_save_wall("Temp Wall", {})
    await wall_manager.async_delete_wall(created["wall_id"])
    assert await wall_manager.async_get_wall(created["wall_id"]) is None


async def test_duplicate_wall_name_rejected(wall_manager):
    await wall_manager.async_save_wall("Living Room", {})
    with pytest.raises(WallError, match="already exists"):
        await wall_manager.async_save_wall("Living Room", {})


async def test_empty_wall_name_rejected(wall_manager):
    with pytest.raises(WallError, match="can't be empty"):
        await wall_manager.async_save_wall("  ", {})


async def test_update_of_deleted_wall_fails_cleanly(wall_manager):
    created = await wall_manager.async_save_wall("Temp", {})
    await wall_manager.async_delete_wall(created["wall_id"])

    with pytest.raises(WallError, match="not found"):
        await wall_manager.async_save_wall("Temp2", {}, wall_id=created["wall_id"])


# ---------------------------------------------------------------------------
# Default wall: non-renamable, non-deletable, auto-syncs with frame entries
# ---------------------------------------------------------------------------


async def test_default_wall_auto_creates_and_tracks_configured_frames(
    hass, wall_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="entry-1")
    entry.add_to_hass(hass)

    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert default_wall is not None
    assert default_wall.kind == KIND_DEFAULT
    assert entry.entry_id in default_wall.placements


async def test_default_wall_rename_is_ignored(hass, wall_manager):
    await wall_manager.async_ensure_default_wall()
    result = await wall_manager.async_save_wall(
        "Something Else", {}, wall_id=DEFAULT_WALL_ID
    )
    assert result["name"] == DEFAULT_WALL_NAME


async def test_default_wall_delete_rejected(hass, wall_manager):
    await wall_manager.async_ensure_default_wall()
    with pytest.raises(WallError, match="can't be deleted"):
        await wall_manager.async_delete_wall(DEFAULT_WALL_ID)


async def test_default_wall_scenes_hub_entry_excluded(hass, wall_manager, make_scenes_hub_entry):
    hub = make_scenes_hub_entry()
    hub.add_to_hass(hass)

    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert hub.entry_id not in default_wall.placements


async def test_tombstone_excluded_frame_survives_resync(
    hass, wall_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="entry-1")
    entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    del default_wall.placements[entry.entry_id]
    default_wall.excluded.append(entry.entry_id)

    # A resync (e.g. HA restart, another frame added) must not resurrect a
    # deliberately-excluded frame.
    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert entry.entry_id not in default_wall.placements
    assert entry.entry_id in default_wall.excluded


async def test_removed_and_readded_frame_gets_fresh_placement(
    hass, wall_manager, make_frame_entry
):
    # Tombstones are keyed on entry_id, which changes on physical
    # remove+re-add -- a "re-added" frame is a brand new entry_id and must
    # not inherit the old exclusion.
    old_entry = make_frame_entry(entry_id="entry-old", device_key="same-frame")
    old_entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    await wall_manager.async_prune_entry(old_entry.entry_id)

    new_entry = make_frame_entry(entry_id="entry-new", device_key="same-frame")
    new_entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert new_entry.entry_id in default_wall.placements


async def test_prune_entry_removes_from_every_wall(hass, wall_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="entry-1")
    entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()
    custom = await wall_manager.async_save_wall(
        "Custom", {entry.entry_id: {"x": 1, "y": 1}}
    )

    await wall_manager.async_prune_entry(entry.entry_id)

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    custom_wall = await wall_manager.async_get_wall(custom["wall_id"])
    assert entry.entry_id not in default_wall.placements
    assert entry.entry_id not in custom_wall.placements


# ---------------------------------------------------------------------------
# Auto-layout collision math
# ---------------------------------------------------------------------------


async def test_auto_layout_places_frames_without_overlap(
    hass, wall_manager, make_frame_entry
):
    entries = [
        make_frame_entry(entry_id=f"entry-{i}", host=f"192.168.1.{50+i}")
        for i in range(4)
    ]
    for entry in entries:
        entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    positions = [default_wall.placements[e.entry_id] for e in entries]
    # All four fit in _MAX_FRAMES_PER_ROW=4 -- same row, strictly increasing x.
    ys = {p["y"] for p in positions}
    assert len(ys) == 1
    xs = [p["x"] for p in positions]
    assert xs == sorted(xs)
    assert len(set(xs)) == 4


async def test_auto_layout_wraps_to_new_row_after_max_per_row(
    hass, wall_manager, make_frame_entry
):
    entries = [
        make_frame_entry(entry_id=f"entry-{i}", host=f"192.168.1.{50+i}")
        for i in range(5)
    ]
    for entry in entries:
        entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    fifth_pos = default_wall.placements[entries[4].entry_id]
    first_pos = default_wall.placements[entries[0].entry_id]
    assert fifth_pos["y"] > first_pos["y"]


async def test_auto_layout_does_not_overlap_after_removing_and_readding_a_frame(
    hass, wall_manager, make_frame_entry
):
    """Regression: removing one frame from a full row of _MAX_FRAMES_PER_ROW
    (4) can land the placement count back on a multiple of 4, which used to
    make _append_placement wrongly assume that row was empty and place the
    next new frame directly on top of a tile that was never moved."""
    entries = [
        make_frame_entry(entry_id=f"entry-{i}", host=f"192.168.1.{50+i}")
        for i in range(5)
    ]
    for entry in entries:
        entry.add_to_hass(hass)
    await wall_manager.async_ensure_default_wall()

    # Remove one of the first 4 (row 0) frames -- placements count drops
    # from 5 to 4, a multiple of _MAX_FRAMES_PER_ROW, while row 0 still
    # holds 3 live tiles and row 1 still holds entries[4].
    await wall_manager.async_prune_entry(entries[0].entry_id)

    new_entry = make_frame_entry(entry_id="entry-new", host="192.168.1.99")
    new_entry.add_to_hass(hass)
    await wall_manager.async_ensure_placement(new_entry)

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    positions = list(default_wall.placements.values())
    coords = [(p["x"], p["y"]) for p in positions]
    assert len(coords) == len(set(coords)), (
        f"two placements share the same (x, y): {coords}"
    )
