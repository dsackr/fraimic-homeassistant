"""DataUpdateCoordinator for Fraimic frames."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_IMAGE,
    API_INFO,
    CONF_DEVICE_KEY,
    CONF_HOST,
    CONF_MAC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .helpers import device_key_from_info, find_frame_by_device_key, mac_from_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# After this many consecutive poll failures, trigger a subnet rescan to find
# the frame at its new IP.
_FAILURES_BEFORE_RESCAN = 3


class FraimicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a single Fraimic frame for status data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        self.config_entry = config_entry
        self.host: str = config_entry.data[CONF_HOST]
        self.device_key: str = config_entry.data.get(CONF_DEVICE_KEY, "")

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=timedelta(seconds=scan_seconds),
        )

        self._consecutive_failures: int = 0
        self._rescan_in_progress: bool = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self, endpoint: str) -> str:
        return f"http://{self.host}{endpoint}"

    def _maybe_persist_fingerprint(self, data: dict[str, Any]) -> None:
        """Lazy-migrate: store device_key and mac if missing from entry data.

        Entries set up before v0.4.1 won't have these keys. The first
        successful poll after upgrading populates them so DHCP discovery
        can identify the frame on subsequent IP changes.
        """
        needs_update = False
        updates: dict[str, Any] = dict(self.config_entry.data)

        key = device_key_from_info(data)
        if key and not updates.get(CONF_DEVICE_KEY):
            updates[CONF_DEVICE_KEY] = key
            self.device_key = key
            needs_update = True

        mac = mac_from_info(data)
        if mac and not updates.get(CONF_MAC):
            updates[CONF_MAC] = mac
            needs_update = True

        if needs_update:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=updates
            )
            _LOGGER.debug(
                "Stored fingerprint for %s: device_key=%s mac=%s",
                self.host,
                key,
                mac,
            )

    # ------------------------------------------------------------------
    # DataUpdateCoordinator protocol
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the frame's /api/info endpoint."""
        session = async_get_clientsession(self.hass)

        try:
            async with session.get(
                self._base_url(API_INFO), timeout=_REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

            # Successful poll — reset failure counter and migrate fingerprint.
            self._consecutive_failures = 0
            self._maybe_persist_fingerprint(data)
            return data

        except (aiohttp.ClientConnectionError, TimeoutError) as err:
            self._consecutive_failures += 1
            if (
                self._consecutive_failures >= _FAILURES_BEFORE_RESCAN
                and self.device_key
                and not self._rescan_in_progress
            ):
                self.hass.async_create_task(self._async_try_find_new_host())
            raise UpdateFailed(
                "Frame is unreachable — it may be sleeping or off-network"
            ) from err
        except aiohttp.ClientResponseError as err:
            self._consecutive_failures += 1
            raise UpdateFailed(
                f"Frame returned unexpected HTTP {err.status}"
            ) from err
        except Exception as err:  # noqa: BLE001
            self._consecutive_failures += 1
            raise UpdateFailed(f"Unexpected error fetching frame data: {err}") from err

    async def _async_try_find_new_host(self) -> None:
        """Scan the local /24 subnet for the frame's device_key and update host."""
        if self._rescan_in_progress:
            return
        self._rescan_in_progress = True
        try:
            _LOGGER.info(
                "Scanning subnet for Fraimic frame %s (device_key=%s)…",
                self.host,
                self.device_key,
            )
            import socket
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
            except Exception:  # noqa: BLE001
                local_ip = "192.168.1.1"

            new_ip = await find_frame_by_device_key(local_ip, self.device_key)
            if new_ip and new_ip != self.host:
                _LOGGER.info(
                    "Fraimic frame %s found at new IP %s (was %s)",
                    self.device_key,
                    new_ip,
                    self.host,
                )
                self.host = new_ip
                self._consecutive_failures = 0
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_HOST: new_ip},
                )
                await self.async_request_refresh()
            elif new_ip is None:
                _LOGGER.warning(
                    "Fraimic frame %s not found anywhere on subnet",
                    self.device_key,
                )
        finally:
            self._rescan_in_progress = False

    # ------------------------------------------------------------------
    # Config-entry update listener — called when entry data changes
    # (e.g. host updated by the DHCP discovery flow).
    # ------------------------------------------------------------------

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        """Pick up a new host without restarting the integration."""
        new_host = entry.data.get(CONF_HOST, self.host)
        if new_host != self.host:
            _LOGGER.info(
                "Fraimic coordinator %s: host updated to %s", self.device_key, new_host
            )
            self.host = new_host
            self._consecutive_failures = 0
            await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Command helpers called from services / buttons
    # ------------------------------------------------------------------

    async def async_send_command(self, endpoint: str) -> int:
        """POST to the given endpoint and return the HTTP status code."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                self._base_url(endpoint), timeout=_REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                status: int = response.status
                _LOGGER.debug("POST %s → %s", self._base_url(endpoint), status)
                return status
        except aiohttp.ClientError as err:
            _LOGGER.error("Error sending command to %s: %s", self._base_url(endpoint), err)
            raise

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Upload a binary image to the frame."""
        session = async_get_clientsession(self.hass)
        url = self._base_url(API_IMAGE)
        headers = {"Content-Type": "application/octet-stream"}
        try:
            async with session.post(
                url,
                data=image_bytes,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                response.raise_for_status()
                status: int = response.status
                _LOGGER.debug(
                    "Uploaded %d bytes to %s → %s", len(image_bytes), url, status
                )
                return status
        except aiohttp.ClientError as err:
            _LOGGER.error("Error uploading image to %s: %s", url, err)
            raise
