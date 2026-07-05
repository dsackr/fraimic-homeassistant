"""Walls: a virtual layout of a subset of the user's frames, positioned the
way they're physically hung (e.g. 4 frames on the living room wall).

A wall only stores where each frame sits on a free-form canvas -- it never
stores which images are assigned. Loading a scene onto a wall and saving the
result back is entirely a panel-side operation against the existing scenes
API; walls themselves are pure layout state, never referenced by
automations, voice control, or any entity platform.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGNAL_WALLS_UPDATED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_STORAGE_KEY = f"{DOMAIN}_walls"
_STORAGE_VERSION = 1


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "name": self.name,
            "placements": self.placements,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Wall":
        return cls(
            wall_id=data["wall_id"],
            name=data["name"],
            placements=dict(data.get("placements") or {}),
            created_at=data.get("created_at", 0.0),
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
    ) -> dict[str, Any]:
        """Create a new wall (wall_id=None) or update an existing one."""
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
            wall.name = name
            wall.placements = placements
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
        if wall_id in self._walls:
            del self._walls[wall_id]
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)
