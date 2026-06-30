"""HTTP API views for the Fraimic shared image library.

Endpoints:
    GET  /api/fraimic/library/list           list library images + active backend
    POST /api/fraimic/library/upload         upload a new original (multipart "image")
    GET  /api/fraimic/library/image/{id}     stream an original (for thumbnails)
    POST /api/fraimic/library/send           send a library image to a frame
    GET  /api/fraimic/library/settings       current backend name
    POST /api/fraimic/library/settings       change backend (validates first)
"""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import CONF_HEIGHT, CONF_WIDTH, DOMAIN
from .http_api import resolve_frame_by_entity

_LOGGER = logging.getLogger(__name__)


def _get_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_library")
    if manager is None:
        raise RuntimeError("Library manager not initialised")
    return manager


class FraimicLibraryListView(HomeAssistantView):
    """List every image currently in the library."""

    url = "/api/fraimic/library/list"
    name = "api:fraimic:library:list"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        images = await manager.async_list_images()
        return self.json({"images": images, "backend": manager.backend_name})


class FraimicLibraryUploadView(HomeAssistantView):
    """Upload a new original image into the library.

    Eagerly converts it to a .bin for every resolution currently in use
    across configured frames (see LibraryManager.async_upload).
    """

    url = "/api/fraimic/library/upload"
    name = "api:fraimic:library:upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            data = await request.post()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid request body: {err}", status_code=400)

        image_field = data.get("image")
        if image_field is None:
            return self.json_message("image file is required", status_code=400)

        try:
            raw_bytes: bytes = image_field.file.read()  # type: ignore[union-attr]
            filename = getattr(image_field, "filename", None) or "image"
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Could not read image data: {err}", status_code=400)

        if not raw_bytes:
            return self.json_message("Uploaded file is empty", status_code=400)

        try:
            record = await manager.async_upload(filename, raw_bytes)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Library upload failed: %s", err)
            return self.json_message(f"Upload failed: {err}", status_code=500)

        return self.json({"success": True, "image": record})


class FraimicLibraryImageView(HomeAssistantView):
    """Stream a stored original (GET, for thumbnails) or remove it (DELETE)."""

    url = "/api/fraimic/library/image/{image_id}"
    name = "api:fraimic:library:image"
    requires_auth = True

    async def get(self, request: web.Request, image_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        try:
            raw_bytes, content_type = await manager.async_get_original(image_id)
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Image not found: {err}", status_code=404)
        return web.Response(body=raw_bytes, content_type=content_type)

    async def delete(self, request: web.Request, image_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        try:
            await manager.async_delete(image_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete library image %s: %s", image_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class FraimicLibrarySendView(HomeAssistantView):
    """Send an existing library image to a frame.

    Reuses a cached .bin for that frame's resolution if one exists; otherwise
    converts on the fly and caches the result for next time.
    """

    url = "/api/fraimic/library/send"
    name = "api:fraimic:library:send"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.post()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid request body: {err}", status_code=400)

        entity_id = body.get("entity_id")
        image_id = body.get("image_id")

        if not entity_id:
            return self.json_message("entity_id is required", status_code=400)
        if not image_id:
            return self.json_message("image_id is required", status_code=400)

        try:
            coordinator, entry = resolve_frame_by_entity(hass, entity_id)
        except ValueError as err:
            return self.json_message(str(err), status_code=404)

        width: int = entry.data[CONF_WIDTH]
        height: int = entry.data[CONF_HEIGHT]

        try:
            bin_bytes = await manager.async_get_bin_for_send(image_id, width, height)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Library send conversion failed: %s", err)
            return self.json_message(f"Conversion failed: {err}", status_code=500)

        try:
            await coordinator.async_send_image(bin_bytes)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to send library image to frame %s: %s", coordinator.host, err
            )
            return self.json_message(f"Failed to send to frame: {err}", status_code=502)

        return self.json({"success": True, "bytes_sent": len(bin_bytes)})


class FraimicLibrarySettingsView(HomeAssistantView):
    """Get/set which storage backend the library uses."""

    url = "/api/fraimic/library/settings"
    name = "api:fraimic:library:settings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        return self.json({"backend": manager.backend_name})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            settings = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        if not isinstance(settings, dict) or "backend" not in settings:
            return self.json_message("'backend' field is required", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            await manager.async_set_backend(settings)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to set library backend: %s", err)
            return self.json_message(f"Failed to set backend: {err}", status_code=500)

        return self.json({"success": True, "backend": manager.backend_name})
