"""Walls: a virtual layout of a subset of the user's frames, positioned the
way they're physically hung (e.g. 4 frames on the living room wall).

A wall only stores where each frame sits on a free-form canvas -- it never
stores which images are assigned. Loading a scene onto a wall and saving the
result back is entirely a panel-side operation against the existing scenes
API; walls themselves are pure layout state, never referenced by
automations, voice control, or any entity platform.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    CONF_HEIGHT,
    CONF_ORIENTATION,
    CONF_WIDTH,
    DOMAIN,
    KIND_SCENES_HUB,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    SIGNAL_WALLS_UPDATED,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_STORAGE_KEY = f"{DOMAIN}_walls"
_STORAGE_VERSION = 1

# The default wall: a real Wall record with a fixed sentinel id, guaranteed
# to exist and to hold a placement for every configured frame. Non-deletable
# and non-renamable; otherwise behaves exactly like a custom wall.
DEFAULT_WALL_ID = "default"
DEFAULT_WALL_NAME = "All Frames"
KIND_DEFAULT = "default"
KIND_CUSTOM = "custom"

# Mirror of digital-frames-panel.js's _wallTileDims normalization and GRID snap --
# auto-appended placements must use the same tile geometry the canvas
# renders with, or a new tile could land overlapping an existing one.
# Keep these in sync with the panel.
_TILE_TARGET_LONGEST = 140
_GRID = 20

# Auto-layout-only geometry for the default wall (custom walls have no such
# limit -- users free-place those). A tile's longest edge is always scaled
# to _TILE_TARGET_LONGEST regardless of orientation, so this cell size fits
# any tile without vertical collisions between rows.
_MAX_FRAMES_PER_ROW = 4
_CELL = _TILE_TARGET_LONGEST + _GRID
# Two rows/columns of empty breathing room above and left of the first
# auto-placed tile, instead of starting flush in the corner.
_MARGIN_LEFT = _CELL * 2
_MARGIN_TOP = _CELL * 2


def tile_dims(entry: "ConfigEntry") -> tuple[int, int]:
    """A frame's on-canvas tile size (px), aspect-correct and orientation-
    aware -- the backend twin of the panel's _wallTileDims."""
    width = entry.data.get(CONF_WIDTH) or 1200
    height = entry.data.get(CONF_HEIGHT) or 1600
    orientation = entry.options.get(CONF_ORIENTATION)
    if orientation == ORIENTATION_PORTRAIT and width > height:
        width, height = height, width
    if orientation == ORIENTATION_LANDSCAPE and height > width:
        width, height = height, width
    scale = _TILE_TARGET_LONGEST / max(width, height)
    return round(width * scale), round(height * scale)


class WallError(Exception):
    """Raised for invalid wall operations (bad name, not found)."""


@dataclass
class Wall:
    """A named set of (frame entry_id -> canvas position) placements."""

    wall_id: str
    name: str
    # entry_id -> {"x": .., "y": ..}. Free-form canvas position, not a fixed
    # N×M cell grid -- frames come in different physical sizes/orientations
    # and real gallery walls aren't always a strict matrix. Snapping to a
    # grid unit is purely a client-side drag convenience.
    placements: dict[str, dict[str, float]] = field(default_factory=dict)
    created_at: float = 0.0
    # KIND_DEFAULT for the auto-synced default wall, KIND_CUSTOM otherwise.
    # Walls stored before this field existed deserialize as custom.
    kind: str = KIND_CUSTOM
    # Entry_ids the user deliberately removed from the default wall.
    # Without this tombstone list, the auto-sync would resurrect every
    # removed frame at the next restart. Meaningless on custom walls
    # (absence from placements already says everything there).
    excluded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "name": self.name,
            "placements": self.placements,
            "created_at": self.created_at,
            "kind": self.kind,
            "excluded": self.excluded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Wall":
        return cls(
            wall_id=data["wall_id"],
            name=data["name"],
            placements=dict(data.get("placements") or {}),
            created_at=data.get("created_at", 0.0),
            kind=data.get("kind") or KIND_CUSTOM,
            excluded=list(data.get("excluded") or []),
        )


class WallManager:
    """Owns the set of user-defined wall layouts."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._walls: dict[str, Wall] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        for data in (stored or {}).get("walls", []):
            wall = Wall.from_dict(data)
            self._walls[wall.wall_id] = wall

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"walls": [wall.to_dict() for wall in self._walls.values()]}
        )

    def _frame_entries(self) -> list["ConfigEntry"]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("kind") != KIND_SCENES_HUB
        ]

    def _append_placement(self, wall: Wall, entry: "ConfigEntry") -> None:
        """Place *entry* in the next open grid slot: rows of up to
        _MAX_FRAMES_PER_ROW tiles, filled left-to-right and wrapping onto a
        new row underneath, starting _MARGIN_LEFT/_MARGIN_TOP in from the
        canvas edges rather than flush in the corner. Deterministic and
        collision-free by construction; the user drags it wherever they
        want afterwards. This shape is specific to auto-populating the
        default wall -- custom walls have no such row limit.

        The target row always scans for its *actual* current occupants
        rather than trusting `len(wall.placements) % _MAX_FRAMES_PER_ROW ==
        0` to mean "this row is empty" -- after a frame is removed from a
        full row and a new one is added, that count can land back on a
        multiple of _MAX_FRAMES_PER_ROW while the row still holds tiles,
        which used to place the new tile directly on top of a survivor."""
        row = len(wall.placements) // _MAX_FRAMES_PER_ROW
        y = _MARGIN_TOP + row * _CELL
        right_edge = _MARGIN_LEFT
        occupied = False
        for entry_id, pos in wall.placements.items():
            if pos["y"] != y:
                continue
            occupied = True
            placed = self.hass.config_entries.async_get_entry(entry_id)
            width = tile_dims(placed)[0] if placed else _TILE_TARGET_LONGEST
            right_edge = max(right_edge, pos["x"] + width)
        x = _MARGIN_LEFT if not occupied else math.ceil(right_edge / _GRID) * _GRID + _GRID
        wall.placements[entry.entry_id] = {"x": float(x), "y": float(y)}

    async def async_ensure_default_wall(self) -> None:
        """Create the default wall if missing, then reconcile its placements
        against the configured frame entries (add missing, prune stale).
        Called once from async_setup; safe to call repeatedly."""
        changed = False
        wall = self._walls.get(DEFAULT_WALL_ID)
        if wall is None:
            wall = Wall(
                wall_id=DEFAULT_WALL_ID,
                name=DEFAULT_WALL_NAME,
                kind=KIND_DEFAULT,
                created_at=time.time(),
            )
            self._walls[DEFAULT_WALL_ID] = wall
            changed = True

        entries = self._frame_entries()
        entry_ids = {entry.entry_id for entry in entries}
        for stale_id in [eid for eid in wall.placements if eid not in entry_ids]:
            del wall.placements[stale_id]
            changed = True
        stale_excluded = [eid for eid in wall.excluded if eid not in entry_ids]
        if stale_excluded:
            wall.excluded = [eid for eid in wall.excluded if eid in entry_ids]
            changed = True
        for entry in entries:
            if (
                entry.entry_id not in wall.placements
                and entry.entry_id not in wall.excluded
            ):
                self._append_placement(wall, entry)
                changed = True

        if changed:
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_ensure_placement(self, entry: "ConfigEntry") -> None:
        """Guarantee *entry* has a spot on the default wall (unless the user
        deliberately removed it -- see Wall.excluded). Called from
        async_setup_entry, so it covers every way a frame arrives (embedded
        add, discovery flow, HA restart). Idempotent."""
        wall = self._walls.get(DEFAULT_WALL_ID)
        if wall is None:
            # async_setup creates the default wall before any entry sets up;
            # this is belt-and-braces for a reload racing that.
            await self.async_ensure_default_wall()
            return
        if entry.entry_id in wall.placements or entry.entry_id in wall.excluded:
            return
        self._append_placement(wall, entry)
        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_prune_entry(self, entry_id: str) -> None:
        """Drop *entry_id*'s placement from every wall (default and custom)
        when its config entry is removed -- otherwise deleted frames haunt
        wall layouts forever (CODE_REVIEW #28). Tombstones die with the
        entry too: a frame removed and re-added gets a fresh entry_id, so a
        stale exclusion could never match it anyway."""
        changed = False
        for wall in self._walls.values():
            if entry_id in wall.placements:
                del wall.placements[entry_id]
                changed = True
            if entry_id in wall.excluded:
                wall.excluded.remove(entry_id)
                changed = True
        if changed:
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_list_walls(self) -> list[dict[str, Any]]:
        return [wall.to_dict() for wall in self._walls.values()]

    async def async_get_wall(self, wall_id: str) -> Wall | None:
        return self._walls.get(wall_id)

    async def async_get_wall_by_name(self, name: str) -> Wall | None:
        name = (name or "").strip().lower()
        for wall in self._walls.values():
            if wall.name.strip().lower() == name:
                return wall
        return None

    async def async_save_wall(
        self,
        name: str,
        placements: dict[str, dict[str, float]],
        wall_id: str | None = None,
        excluded: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new wall (wall_id=None) or update an existing one.
        *excluded* of None means "leave the stored tombstones unchanged"."""
        name = (name or "").strip()
        if not name:
            raise WallError("Wall name can't be empty")

        placements = {
            entry_id: {"x": float(pos["x"]), "y": float(pos["y"])}
            for entry_id, pos in (placements or {}).items()
            if entry_id and isinstance(pos, dict) and "x" in pos and "y" in pos
        }

        if wall_id is not None and wall_id not in self._walls:
            # Updating a wall that's gone (e.g. deleted from another tab
            # since this edit was opened) must fail, not silently resurrect
            # it under its old id with whatever's in this stale form.
            raise WallError(f"Wall '{wall_id}' not found")

        existing_by_name = await self.async_get_wall_by_name(name)
        if existing_by_name is not None and existing_by_name.wall_id != wall_id:
            raise WallError(f"A wall named '{name}' already exists")

        if wall_id is not None:
            wall = self._walls[wall_id]
            if wall.kind == KIND_DEFAULT:
                # The default wall accepts layout changes but keeps its
                # identity -- a rename would break the panel's "this is
                # every frame" anchor.
                wall.placements = placements
            else:
                wall.name = name
                wall.placements = placements
            if excluded is not None:
                wall.excluded = [
                    e for e in excluded if isinstance(e, str) and e
                ]
        else:
            wall = Wall(
                wall_id=uuid.uuid4().hex[:12],
                name=name,
                placements=placements,
                created_at=time.time(),
            )
            self._walls[wall.wall_id] = wall

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)
        return wall.to_dict()

    async def async_delete_wall(self, wall_id: str) -> None:
        wall = self._walls.get(wall_id)
        if wall is None:
            return
        if wall.kind == KIND_DEFAULT:
            raise WallError("The default wall can't be deleted")
        del self._walls[wall_id]
        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)
