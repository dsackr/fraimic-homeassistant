"""DataUpdateCoordinator for local Meural Canvas frames (FramePort Phase 3)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from .meural import (
    meural_orientation_from_payload,
    meural_system_info,
    probe_meural,
    send_meural_postcard,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PREVIEW_STORE_VERSION = 1


class MeuralCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a single local Meural and delivers JPEG postcards.

    Duck-types the FraimicCoordinator surface used by scenes, library send,
    walls list, and preview storage so core product code stays driver-agnostic.
    """

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.host: str = config_entry.data[CONF_HOST]
        self.device_key: str = config_entry.data.get("device_key", "") or f"meural:{self.host}"

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} meural {self.host}",
            update_interval=timedelta(seconds=scan_seconds),
            config_entry=config_entry,
        )
        # Keep an explicit ref for duck-typing with FraimicCoordinator and for
        # tests that pass a simple MagicMock entry (some HA versions only
        # attach config_entry via the super() kwarg above).
        self.config_entry = config_entry

        self.last_image_id: str | None = None
        self.last_thumbnail: bytes | None = None
        # Meural local postcard has no Fraimic-style sleep queue.
        self.pending_send: dict[str, Any] | None = None

        self._preview_store = Store(
            hass,
            _PREVIEW_STORE_VERSION,
            f"{DOMAIN}_meural_preview_{config_entry.entry_id}",
        )

    async def async_load_last_image(self) -> None:
        data = await self._preview_store.async_load()
        if not isinstance(data, dict):
            return
        self.last_image_id = data.get("image_id")
        thumb_b64 = data.get("thumbnail_b64")
        if thumb_b64:
            import base64  # noqa: PLC0415

            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception:  # noqa: BLE001
                self.last_thumbnail = None

    async def async_load_pending_send(self) -> None:
        """No-op: Meural driver does not queue sends on sleep."""
        return

    async def async_set_last_image(
        self,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> None:
        import base64  # noqa: PLC0415

        self.last_image_id = image_id
        self.last_thumbnail = thumbnail
        await self._preview_store.async_save(
            {
                "image_id": image_id,
                "thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
            }
        )

    async def _async_update_data(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        info = await probe_meural(session, self.host)
        if info is None:
            raise UpdateFailed(f"Meural at {self.host} unreachable")
        system = await meural_system_info(session, self.host)
        device_orientation = meural_orientation_from_payload(
            system
        ) or meural_orientation_from_payload(info)

        wifi_ip: str | None = None
        if isinstance(info, dict) and info.get("wifi_ip"):
            wifi_ip = str(info["wifi_ip"])
        if wifi_ip is None and isinstance(system, dict):
            wifi_status = system.get("wifi_status")
            if isinstance(wifi_status, dict) and wifi_status.get("ip"):
                wifi_ip = str(wifi_status["ip"])

        data: dict[str, Any] = {
            "driver": "meural",
            "host": self.host,
            "identify": info,
            "firmware_version": None,
            "device_orientation": device_orientation,
            "ip_address": wifi_ip or self.host,
        }

        if system:
            data["system"] = system
            # Best-effort common keys — field names vary by firmware.
            for key in ("version", "firmware", "fw_version", "sw_version"):
                if key in system and system[key]:
                    data["firmware_version"] = str(system[key])
                    break
            if not data.get("firmware_version") and system.get("version"):
                data["firmware_version"] = str(system["version"])

        if device_orientation in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE):
            self.hass.async_create_task(
                self._async_maybe_follow_device_orientation(device_orientation)
            )
        return data

    async def _async_maybe_follow_device_orientation(self, device_orientation: str) -> None:
        """When follow-device is on, mirror gsensor into entry.options.orientation.

        That drives render_spec / crop aspect / wall tile size. Only writes when
        the value changes (async_update_entry reloads the entry).
        """
        entry = self.config_entry
        follow = entry.options.get(CONF_ORIENTATION_FOLLOW_DEVICE, True)
        if not follow:
            return
        if entry.options.get(CONF_ORIENTATION) == device_orientation:
            return
        self.hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_ORIENTATION: device_orientation,
                CONF_ORIENTATION_FOLLOW_DEVICE: True,
            },
        )

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        new_host = entry.data.get(CONF_HOST, self.host)
        if new_host != self.host:
            _LOGGER.info("Meural coordinator host updated to %s", new_host)
            self.host = new_host
            await self.async_request_refresh()

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Upload JPEG (or other image) bytes as a Meural postcard."""
        session = async_get_clientsession(self.hass)
        content_type = "image/jpeg"
        # Detect PNG magic if raw upload path ever passes PNG.
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            content_type = "image/png"
        await send_meural_postcard(
            session, self.host, image_bytes, content_type=content_type
        )
        return 200

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        """Send immediately. Meural has no Fraimic-style queue-if-asleep."""
        try:
            await self.async_send_image(image_bytes)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.error("Meural send to %s failed: %s", self.host, err)
            return {"success": False, "queued": False, "message": str(err)}
        await self.async_set_last_image(image_id=image_id, thumbnail=thumbnail)
        return {"success": True, "queued": False}

    async def async_send_command(self, endpoint: str) -> int:
        """Best-effort remote control path (suspend/resume etc.)."""
        session = async_get_clientsession(self.hass)
        url = f"http://{self.host}/remote/{endpoint.lstrip('/')}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return resp.status
