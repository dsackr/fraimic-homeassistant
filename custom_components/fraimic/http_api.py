"""HTTP API views — image uploads to a frame, and the onboarding flag."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .helpers import render_spec_for_hass_entry

_LOGGER = logging.getLogger(__name__)


class FraimicSamsungContentView(HomeAssistantView):
    """Unauthenticated token URL for Samsung MDC content-download pulls.

    The panel fetches PNG without HA cookies; security is the unguessable
    token (staged per send, short TTL). Protocol pattern from fayep/Joyous.
    """

    url = "/api/fraimic/samsung/{token}/content.png"
    name = "api:fraimic:samsung:content"
    requires_auth = False

    async def get(self, request: web.Request, token: str) -> web.Response:
        hass = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        for key, coord in domain_data.items():
            if str(key).startswith("_"):
                continue
            getter = getattr(coord, "get_staged_content", None)
            if not callable(getter):
                continue
            body = getter(token)
            if body is not None:
                return web.Response(
                    body=body,
                    content_type="image/png",
                    headers={"Cache-Control": "no-store"},
                )
        return web.Response(status=404, text="Not found")

_ONBOARDING_STORE_KEY = f"{DOMAIN}_onboarding"
_ONBOARDING_STORE_VERSION = 1


class FraimicOnboardingView(HomeAssistantView):
    """GET/POST /api/fraimic/onboarding — the first-run wizard's flag.

    Server-side (an HA Store, not localStorage) so completing or skipping
    the wizard once dismisses it for every admin on every browser, forever.
    """

    url = "/api/fraimic/onboarding"
    name = "api:fraimic:onboarding"
    requires_auth = True

    def _store(self, hass) -> Store:
        domain_data = hass.data.setdefault(DOMAIN, {})
        store = domain_data.get("_onboarding_store")
        if store is None:
            store = Store(hass, _ONBOARDING_STORE_VERSION, _ONBOARDING_STORE_KEY)
            domain_data["_onboarding_store"] = store
        return store

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        data = await self._store(hass).async_load() or {}
        return self.json({"complete": bool(data.get("complete"))})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        # Only admins ever see the wizard (its actions -- config flows,
        # backend switching -- are admin capabilities), so only admins may
        # retire it for the whole install.
        if not request["hass_user"].is_admin:
            return self.json_message("Admin required", status_code=403)
        await self._store(hass).async_save({"complete": True})
        return self.json({"success": True, "complete": True})


def _is_frame_coordinator(obj) -> bool:
    """True for FraimicCoordinator / MeuralCoordinator (not domain helpers)."""
    return (
        obj is not None
        and hasattr(obj, "async_send_image_or_queue")
        and hasattr(obj, "host")
    )


def resolve_frame_by_entity(hass, entity_id: str):
    """Resolve a frame entity_id to (coordinator, config_entry).

    Shared by send/upload HTTP views. Prefers the entity registry's
    ``config_entry_id`` (reliable for Meural IP sensors and Fraimic battery
    sensors). Falls back to the device registry's config_entries set.

    Raises ValueError with a user-facing message on any resolution failure.
    """
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get(entity_id)
    if entity_entry is None:
        raise ValueError(f"Entity '{entity_id}' not found")

    domain_data: dict = hass.data.get(DOMAIN, {})

    # 1) Entity → config entry (Meural often fails path 2 if the device has
    #    not fully linked config_entries after a multi-platform setup).
    entry_id = getattr(entity_entry, "config_entry_id", None)
    if entry_id:
        coordinator = domain_data.get(entry_id)
        if _is_frame_coordinator(coordinator):
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                return coordinator, entry

    # 2) Device registry → any domain entry with a frame coordinator
    if entity_entry.device_id:
        dev_reg = dr.async_get(hass)
        device_entry = dev_reg.async_get(entity_entry.device_id)
        if device_entry is not None:
            for eid in device_entry.config_entries:
                coordinator = domain_data.get(eid)
                if not _is_frame_coordinator(coordinator):
                    continue
                entry = hass.config_entries.async_get_entry(eid)
                if entry is not None:
                    return coordinator, entry

    raise ValueError(
        "No frame coordinator found for this device "
        "(reload the Fraimic integration if you just added a Meural)"
    )


class FraimicFrameStatusView(HomeAssistantView):
    """GET /api/fraimic/frame_status?entity_id=... — resolve any Fraimic
    entity to its frame's on-frame preview info, for the standalone Lovelace
    card (fraimic-card.js). The sidebar panel resolves this itself via
    admin-only config_entries/device_registry websocket calls, which a card
    on a non-admin's dashboard can't use -- this endpoint does the same
    resolve_frame_by_entity lookup server-side so any authenticated user's
    card can show the current on-frame thumbnail.
    """

    url = "/api/fraimic/frame_status"
    name = "api:fraimic:frame_status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        entity_id = request.query.get("entity_id")
        if not entity_id:
            return self.json_message("entity_id is required", status_code=400)

        try:
            coordinator, entry = resolve_frame_by_entity(hass, entity_id)
        except ValueError as err:
            return self.json_message(str(err), status_code=404)

        return self.json(
            {
                "entry_id": entry.entry_id,
                "last_image_id": coordinator.last_image_id,
                "has_thumbnail": coordinator.last_thumbnail is not None,
                "queued": coordinator.pending_send is not None,
            }
        )


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
        # image_field.file is a spooled temp file -- .read() is blocking I/O
        # and must not run directly on the event loop (it would stall every
        # other request for the duration of a multi-MB read).
        try:
            raw_bytes: bytes = await hass.async_add_executor_job(
                image_field.file.read  # type: ignore[union-attr]
            )
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Could not read image data: {err}", status_code=400)

        if not raw_bytes:
            return self.json_message("Uploaded file is empty", status_code=400)

        # Resolve entity_id → device → config entry → coordinator.
        try:
            coordinator, entry = resolve_frame_by_entity(hass, entity_id)
        except ValueError as err:
            return self.json_message(str(err), status_code=404)

        spec = render_spec_for_hass_entry(hass, entry)

        # PanelCodec seam — Spectra layout or Meural JPEG from entry driver.
        from .panel_codec import (  # noqa: PLC0415
            encode_for_panel_with_preview,
            panel_codec_for_entry,
        )

        try:
            codec_id = panel_codec_for_entry(entry).id
        except ValueError:
            codec_id = None

        try:
            bin_bytes, preview_bytes = await hass.async_add_executor_job(
                encode_for_panel_with_preview,
                raw_bytes,
                spec.width,
                spec.height,
                spec.rotation,
                spec.locked,
                codec_id,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Image conversion failed for %s: %s", coordinator.host, err)
            return self.json_message(
                f"Image conversion failed: {err}", status_code=500
            )

        # Upload to the frame, or queue it if the frame is asleep.
        # async_send_image_or_queue already updates the Frames panel's
        # thumbnail hint (last_thumbnail -- this upload has no Library
        # image_id) on success.
        try:
            result = await coordinator.async_send_image_or_queue(
                bin_bytes, thumbnail=preview_bytes
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to send image to frame %s: %s", coordinator.host, err
            )
            return self.json_message(
                f"Failed to send to frame: {err}", status_code=502
            )

        if result["queued"]:
            _LOGGER.info(
                "Frame %s unreachable — image queued for delivery on wake",
                coordinator.host,
            )
            return self.json(
                {
                    "success": False,
                    "queued": True,
                    "message": (
                        "Frame is asleep — the image is queued and will be "
                        "sent when it wakes up."
                    ),
                }
            )

        _LOGGER.info(
            "Image sent to frame %s (%d raw bytes → %d bin bytes)",
            coordinator.host,
            len(raw_bytes),
            len(bin_bytes),
        )
        return self.json({"success": True, "queued": False, "bytes_sent": len(bin_bytes)})
