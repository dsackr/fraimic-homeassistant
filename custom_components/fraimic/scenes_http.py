"""HTTP API views for Fraimic scenes.

Endpoints:
    GET    /api/fraimic/scenes                 list scenes
    POST   /api/fraimic/scenes                 create a scene ({name, mappings})
    POST   /api/fraimic/scenes/{scene_id}       update a scene ({name, mappings})
    DELETE /api/fraimic/scenes/{scene_id}       delete a scene
    POST   /api/fraimic/scenes/{scene_id}/send  send a scene now
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_scene_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_scenes")
    if manager is None:
        raise RuntimeError("Scene manager not initialised")
    return manager


def _parse_scene_body(body: Any) -> tuple[str | None, dict]:
    # body is whatever request.json() decoded -- could be a list, number, or
    # string for a syntactically-valid but wrongly-shaped request.
    if not isinstance(body, dict):
        return None, {}
    name = body.get("name")
    mappings = body.get("mappings")
    if not isinstance(mappings, dict):
        mappings = {}
    return name, mappings


class FraimicScenesView(HomeAssistantView):
    """List (GET) or create (POST) scenes."""

    url = "/api/fraimic/scenes"
    name = "api:fraimic:scenes"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_scene_manager(hass)
        scenes = await manager.async_list_scenes()
        return self.json({"scenes": scenes})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_scene_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, mappings = _parse_scene_body(body)

        from .scenes import SceneError  # noqa: PLC0415

        try:
            scene = await manager.async_save_scene(name, mappings)
        except SceneError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create scene: %s", err)
            return self.json_message(f"Failed to create scene: {err}", status_code=500)

        return self.json({"success": True, "scene": scene})


class FraimicSceneView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single scene."""

    url = "/api/fraimic/scenes/{scene_id}"
    name = "api:fraimic:scenes:one"
    requires_auth = True

    async def post(self, request: web.Request, scene_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_scene_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, mappings = _parse_scene_body(body)

        from .scenes import SceneError  # noqa: PLC0415

        try:
            scene = await manager.async_save_scene(name, mappings, scene_id=scene_id)
        except SceneError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update scene '%s': %s", scene_id, err)
            return self.json_message(f"Failed to update scene: {err}", status_code=500)

        return self.json({"success": True, "scene": scene})

    async def delete(self, request: web.Request, scene_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_scene_manager(hass)
        try:
            await manager.async_delete_scene(scene_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete scene '%s': %s", scene_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class FraimicSceneSendView(HomeAssistantView):
    """Send every image in a scene to its assigned frame."""

    url = "/api/fraimic/scenes/{scene_id}/send"
    name = "api:fraimic:scenes:send"
    requires_auth = True

    async def post(self, request: web.Request, scene_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_scene_manager(hass)

        from .scenes import SceneError  # noqa: PLC0415

        try:
            result = await manager.async_send_scene(hass, scene_id)
        except SceneError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to send scene '%s': %s", scene_id, err)
            return self.json_message(f"Failed to send scene: {err}", status_code=500)

        results = result.get("results", [])
        # "success" means the whole scene sent -- a caller that only checks
        # this field (rather than every entry in `results`) shouldn't be
        # told a scene succeeded when only some of its frames did.
        success = bool(results) and all(r.get("success") for r in results)
        return self.json({"success": success, "results": results})
