"""DataUpdateCoordinator for Samsung EM32DX (experimental)."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    CONF_HOST,
    CONF_MAC,
    CONF_MDC_PIN,
    DEFAULT_MDC_PIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SAMSUNG_MDC_PORT,
)
from .samsung import mdc_port_open, send_mdc_content_download, send_wol

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PREVIEW_STORE_VERSION = 1
# Keep staged PNG fetchable while the panel wakes / downloads.
_CONTENT_TTL_SEC = 600


class SamsungCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push PNG via MDC content-download + HA-hosted token URL.

    Duck-types Fraimic/Meural coordinator surface used by library send,
    scenes, walls, and preview storage.
    """

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.host: str = config_entry.data[CONF_HOST]
        self.device_key: str = (
            config_entry.data.get("device_key", "") or f"samsung:{self.host}"
        )
        self.mdc_pin: str = str(
            config_entry.data.get(CONF_MDC_PIN) or DEFAULT_MDC_PIN
        )
        self.mac: str = str(config_entry.data.get(CONF_MAC) or "")

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} samsung {self.host}",
            update_interval=timedelta(seconds=scan_seconds),
            config_entry=config_entry,
        )
        self.config_entry = config_entry

        self.last_image_id: str | None = None
        self.last_thumbnail: bytes | None = None
        self.pending_send: dict[str, Any] | None = None

        self._content_token: str | None = None
        self._content_bytes: bytes | None = None
        self._content_expires: float = 0.0

        self._preview_store = Store(
            hass,
            _PREVIEW_STORE_VERSION,
            f"{DOMAIN}_samsung_preview_{config_entry.entry_id}",
        )

    async def async_load_last_image(self) -> None:
        data = await self._preview_store.async_load()
        if not isinstance(data, dict):
            return
        import base64  # noqa: PLC0415

        self.last_image_id = data.get("image_id")
        thumb_b64 = data.get("thumbnail_b64")
        if thumb_b64:
            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception:  # noqa: BLE001
                self.last_thumbnail = None

    async def async_load_pending_send(self) -> None:
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

    def stage_content(self, image_bytes: bytes) -> str:
        """Stage PNG bytes; return content token for the public fetch URL."""
        self._content_token = secrets.token_urlsafe(18)
        self._content_bytes = image_bytes
        self._content_expires = time.time() + _CONTENT_TTL_SEC
        return self._content_token

    def get_staged_content(self, token: str) -> bytes | None:
        if not token or token != self._content_token:
            return None
        if time.time() > self._content_expires:
            return None
        return self._content_bytes

    def content_url(self, token: str) -> str:
        base = get_url(
            self.hass,
            prefer_external=False,
            allow_cloud=False,
            allow_external=True,
        ).rstrip("/")
        return f"{base}/api/fraimic/samsung/{token}/content.png"

    async def _async_update_data(self) -> dict[str, Any]:
        reachable = await self.hass.async_add_executor_job(
            mdc_port_open, self.host, SAMSUNG_MDC_PORT, 2.0
        )
        # Asleep panels often refuse MDC — do not raise; just mark offline.
        return {
            "driver": "samsung",
            "host": self.host,
            "reachable": reachable,
            "mdc_port": SAMSUNG_MDC_PORT,
            "ip_address": self.host,
            "firmware_version": None,
            "device_orientation": None,
        }

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        self.host = entry.data.get(CONF_HOST, self.host)
        self.mdc_pin = str(entry.data.get(CONF_MDC_PIN) or DEFAULT_MDC_PIN)
        self.mac = str(entry.data.get(CONF_MAC) or "")
        await self.async_request_refresh()

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Stage PNG, optional WoL, MDC content-download."""
        # Normalize to PNG if JPEG was somehow passed.
        if image_bytes[:2] == b"\xff\xd8":
            image_bytes = await self.hass.async_add_executor_job(
                _jpeg_to_png, image_bytes
            )
        token = self.stage_content(image_bytes)
        url = self.content_url(token)
        if len(url.encode("utf-8")) > 255:
            raise HomeAssistantError(
                "Samsung content URL exceeds MDC 255-byte limit; "
                "use a shorter Home Assistant internal URL"
            )

        if self.mac:
            try:
                await self.hass.async_add_executor_job(send_wol, self.mac)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Samsung WoL failed: %s", err)

        try:
            result = await self.hass.async_add_executor_job(
                send_mdc_content_download,
                self.host,
                url,
                self.mdc_pin,
            )
        except Exception as err:
            _LOGGER.error("Samsung MDC send to %s failed: %s", self.host, err)
            raise HomeAssistantError(f"Samsung MDC send failed: {err}") from err

        _LOGGER.info(
            "Samsung MDC content download queued on %s (auth ok, resp=%s)",
            self.host,
            result.get("response_hex", "")[:32],
        )
        return 200

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        try:
            await self.async_send_image(image_bytes)
        except (HomeAssistantError, OSError, TimeoutError, ValueError) as err:
            return {"success": False, "queued": False, "message": str(err)}
        await self.async_set_last_image(image_id=image_id, thumbnail=thumbnail)
        return {"success": True, "queued": False}

    async def async_send_command(self, endpoint: str) -> int:
        key = (endpoint or "").strip()
        if key in (API_SLEEP, "/api/sleep", "sleep"):
            # Best-effort: no dedicated sleep command in the minimal RE path yet.
            raise HomeAssistantError(
                "Sleep via MDC is not implemented yet for Samsung (experimental)"
            )
        if key in (API_REFRESH, "/api/refresh", "refresh", "/api/wake", "wake"):
            if self.mac:
                await self.hass.async_add_executor_job(send_wol, self.mac)
                return 200
            raise HomeAssistantError("Configure Wi‑Fi MAC to wake Samsung via WoL")
        if key in (API_RESTART, "/api/restart", "restart"):
            raise HomeAssistantError("Restart is not supported on Samsung EM32DX")
        raise HomeAssistantError(f"Unsupported Samsung command: {endpoint!r}")


def _jpeg_to_png(jpeg_bytes: bytes) -> bytes:
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
