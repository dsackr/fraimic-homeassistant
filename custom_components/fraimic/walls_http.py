"""HTTP API views for Fraimic walls.

Endpoints:
    GET    /api/fraimic/walls               list walls
    POST   /api/fraimic/walls               create a wall ({name, placements})
    POST   /api/fraimic/walls/{wall_id}     update a wall ({name, placements})
    DELETE /api/fraimic/walls/{wall_id}     delete a wall
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_wall_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_walls")
    if manager is None:
        raise RuntimeError("Wall manager not initialised")
    return manager


def _parse_wall_body(body: Any) -> tuple[str | None, dict]:
    # body is whatever request.json() decoded -- could be a list, number, or
    # string for a syntactically-valid but wrongly-shaped request.
    if not isinstance(body, dict):
        return None, {}
    name = body.get("name")
    placements = body.get("placements")
    if not isinstance(placements, dict):
        placements = {}
    return name, placements


class FraimicWallsView(HomeAssistantView):
    """List (GET) or create (POST) walls."""

    url = "/api/fraimic/walls"
    name = "api:fraimic:walls"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)
        walls = await manager.async_list_walls()
        return self.json({"walls": walls})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, placements = _parse_wall_body(body)

        from .walls import WallError  # noqa: PLC0415

        try:
            wall = await manager.async_save_wall(name, placements)
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create wall: %s", err)
            return self.json_message(f"Failed to create wall: {err}", status_code=500)

        return self.json({"success": True, "wall": wall})


class FraimicWallView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single wall."""

    url = "/api/fraimic/walls/{wall_id}"
    name = "api:fraimic:walls:one"
    requires_auth = True

    async def post(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, placements = _parse_wall_body(body)

        from .walls import WallError  # noqa: PLC0415

        try:
            wall = await manager.async_save_wall(name, placements, wall_id=wall_id)
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update wall '%s': %s", wall_id, err)
            return self.json_message(f"Failed to update wall: {err}", status_code=500)

        return self.json({"success": True, "wall": wall})

    async def delete(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        from .walls import WallError  # noqa: PLC0415

        try:
            await manager.async_delete_wall(wall_id)
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete wall '%s': %s", wall_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})
