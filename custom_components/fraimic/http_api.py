"""HTTP API view — accept image uploads and forward to a Fraimic frame."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .helpers import render_spec_for_entry

_LOGGER = logging.getLogger(__name__)


def resolve_frame_by_entity(hass, entity_id: str):
    """Resolve a Fraimic entity_id to (coordinator, config_entry).

    Shared by FraimicSendImageView and the library HTTP views so both the
    direct upload-and-send flow and the library send-from-library flow agree
    on how a frame is located. Raises ValueError with a user-facing message
    on any resolution failure.
    """
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get(entity_id)
    if entity_entry is None:
        raise ValueError(f"Entity '{entity_id}' not found")

    dev_reg = dr.async_get(hass)
    device_entry = (
        dev_reg.async_get(entity_entry.device_id)
        if entity_entry.device_id
        else None
    )
    if device_entry is None:
        raise ValueError("No device found for entity")

    domain_data: dict = hass.data.get(DOMAIN, {})
    coordinator = None
    entry_id_found: str | None = None
    for eid in device_entry.config_entries:
        if eid in domain_data:
            coordinator = domain_data[eid]
            entry_id_found = eid
            break

    if coordinator is None or entry_id_found is None:
        raise ValueError("No Fraimic coordinator found for this device")

    entry = hass.config_entries.async_get_entry(entry_id_found)
    if entry is None:
        raise ValueError("Config entry not found")

    return coordinator, entry


class FraimicSendImageView(HomeAssistantView):
    """Handle POST /api/fraimic/send_image.

    Accepts a multipart form with:
        entity_id   — any sensor entity belonging to the target Fraimic device
        image       — the image file to convert and send
    """

    url = "/api/fraimic/send_image"
    name = "api:fraimic:send_image"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Receive an image upload and forward it to the target frame."""
        hass = request.app["hass"]

        try:
            data = await request.post()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid request body: {err}", status_code=400)

        entity_id: str | None = data.get("entity_id")  # type: ignore[assignment]
        image_field = data.get("image")

        if not entity_id:
            return self.json_message("entity_id is required", status_code=400)
        if image_field is None:
            return self.json_message("image file is required", status_code=400)

        # Read raw image bytes from the uploaded file field.
        try:
            raw_bytes: bytes = image_field.file.read()  # type: ignore[union-attr]
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Could not read image data: {err}", status_code=400)

        if not raw_bytes:
            return self.json_message("Uploaded file is empty", status_code=400)

        # Resolve entity_id → device → config entry → coordinator.
        try:
            coordinator, entry = resolve_frame_by_entity(hass, entity_id)
        except ValueError as err:
            return self.json_message(str(err), status_code=404)

        spec = render_spec_for_entry(entry)

        # Convert image in a thread-pool (CPU-bound Pillow work).
        from .image_converter import convert_image_bytes  # noqa: PLC0415

        try:
            bin_bytes: bytes = await hass.async_add_executor_job(
                convert_image_bytes, raw_bytes, spec.width, spec.height,
                spec.rotation, spec.locked,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Image conversion failed for %s: %s", coordinator.host, err)
            return self.json_message(
                f"Image conversion failed: {err}", status_code=500
            )

        # Upload to the frame.
        try:
            await coordinator.async_send_image(bin_bytes)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to send image to frame %s: %s", coordinator.host, err
            )
            return self.json_message(
                f"Failed to send to frame: {err}", status_code=502
            )

        _LOGGER.info(
            "Image sent to frame %s (%d raw bytes → %d bin bytes)",
            coordinator.host,
            len(raw_bytes),
            len(bin_bytes),
        )
        return self.json({"success": True, "bytes_sent": len(bin_bytes)})
