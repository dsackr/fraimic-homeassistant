"""HTTP API views for Fraimic scene packs.

Endpoints:
    GET    /api/digital_frames/scene_packs                  list available packs + install state
    POST   /api/digital_frames/scene_packs/{pack_id}/install install a pack
    POST   /api/digital_frames/scene_packs/{pack_id}/sync    re-fetch missing/new images for an installed pack
    DELETE /api/digital_frames/scene_packs/{pack_id}         uninstall a pack
"""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_scene_packs")
    if manager is None:
        raise RuntimeError("Scene pack manager not initialised")
    return manager


class DigitalFramesScenePacksView(HomeAssistantView):
    """List every scene pack in the catalog, with install state."""

    url = "/api/digital_frames/scene_packs"
    name = "api:digital_frames:scene_packs"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        from .scene_packs import ScenePackError  # noqa: PLC0415

        try:
            packs = await manager.async_list_available()
        except ScenePackError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to list scene packs: %s", err)
            return self.json_message(f"Failed to list scene packs: {err}", status_code=500)

        return self.json({"packs": packs})


class DigitalFramesScenePackInstallView(HomeAssistantView):
    """Install a Gallery pack: import images; optionally build a scene.

    JSON body (all optional):
      create_scene: bool (art packs; default true) — library-only when false
    """

    url = "/api/digital_frames/scene_packs/{pack_id}/install"
    name = "api:digital_frames:scene_packs:install"
    requires_auth = True

    async def post(self, request: web.Request, pack_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        from .scene_packs import ScenePackError  # noqa: PLC0415

        try:
            try:
                body = await request.json()
            except Exception:
                body = {}
            config_data = body.get("config")
            create_scene = body.get("create_scene", True)
            if not isinstance(create_scene, bool):
                create_scene = str(create_scene).strip().lower() not in (
                    "0",
                    "false",
                    "no",
                )

            result = await manager.async_install_pack(
                pack_id, config_data, create_scene=create_scene
            )
        except ScenePackError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to install scene pack '%s': %s", pack_id, err)
            return self.json_message(f"Failed to install pack: {err}", status_code=500)

        return self.json(result)


class DigitalFramesScenePackSyncView(HomeAssistantView):
    """Re-fetch whatever images an installed pack's catalog entry has that
    this install is missing -- repairs a broken/partial install and picks
    up new images a pack has grown since it was installed."""

    url = "/api/digital_frames/scene_packs/{pack_id}/sync"
    name = "api:digital_frames:scene_packs:sync"
    requires_auth = True

    async def post(self, request: web.Request, pack_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        from .scene_packs import ScenePackError  # noqa: PLC0415

        try:
            result = await manager.async_sync_pack(pack_id)
        except ScenePackError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to sync scene pack '%s': %s", pack_id, err)
            return self.json_message(f"Failed to sync pack: {err}", status_code=500)

        return self.json(result)


class DigitalFramesScenePackUninstallView(HomeAssistantView):
    """Uninstall a scene pack: remove its scene and every image it added."""

    url = "/api/digital_frames/scene_packs/{pack_id}"
    name = "api:digital_frames:scene_packs:one"
    requires_auth = True

    async def delete(self, request: web.Request, pack_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        from .scene_packs import ScenePackError  # noqa: PLC0415

        try:
            await manager.async_uninstall_pack(pack_id)
        except ScenePackError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to uninstall scene pack '%s': %s", pack_id, err)
            return self.json_message(f"Failed to uninstall pack: {err}", status_code=500)

        return self.json({"success": True})
