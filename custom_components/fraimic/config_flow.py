"""Config flow for the Fraimic integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HEIGHT,
    CONF_HOST,
    CONF_NAME,
    CONF_WIDTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FRAME_RESOLUTIONS,
    API_INFO,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

CONF_RESOLUTION = "resolution"
CONF_SCAN_INTERVAL = "scan_interval"
_DEFAULT_RESOLUTION = "14x18"
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_SCAN_TIMEOUT = aiohttp.ClientTimeout(total=0.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _probe_frame(
    session: aiohttp.ClientSession,
    host: str,
    timeout: aiohttp.ClientTimeout,
) -> dict[str, Any] | None:
    """Try GET /api/info on *host*. Return parsed JSON or None on any failure."""
    url = f"http://{host}{API_INFO}"
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                return data
    except Exception:  # noqa: BLE001
        pass
    return None


async def _scan_subnet(host_ip: str) -> list[dict[str, Any]]:
    """
    Probe all 254 host addresses in the /24 subnet of *host_ip* concurrently.

    Returns a list of dicts with keys ``ip`` (the probed address) and ``info``
    (the parsed /api/info JSON) for every address that responded.
    """
    try:
        network = ipaddress.IPv4Network(f"{host_ip}/24", strict=False)
    except ValueError:
        return []

    hosts = [str(h) for h in network.hosts()]

    async with aiohttp.ClientSession() as session:
        tasks = [_probe_frame(session, h, _SCAN_TIMEOUT) for h in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    found: list[dict[str, Any]] = []
    for addr, result in zip(hosts, results):
        if isinstance(result, dict):
            found.append({"ip": addr, "info": result})
    return found


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


class FraimicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fraimic."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._discovered: list[dict[str, Any]] = []
        self._selected_host: str = ""
        self._selected_info: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1 — user (manual IP or leave blank to scan)
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Primary entry point. Auto-scan on first visit; fall back to manual IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get(CONF_HOST, "").strip()

            if not host:
                # User submitted the manual form with no IP — re-scan.
                local_ip = self._get_local_ip()
                self._discovered = await _scan_subnet(local_ip)
                if self._discovered:
                    return await self.async_step_pick_device()
                errors["base"] = "no_devices_found"
            else:
                # Manual IP path — probe then go to name_device.
                async with aiohttp.ClientSession() as session:
                    info = await _probe_frame(session, host, _PROBE_TIMEOUT)

                if info is None:
                    errors[CONF_HOST] = "cannot_connect"
                else:
                    self._selected_host = host
                    self._selected_info = info
                    return await self.async_step_name_device()

        else:
            # First visit — auto-scan before showing anything.
            local_ip = self._get_local_ip()
            self._discovered = await _scan_subnet(local_ip)
            if self._discovered:
                return await self.async_step_pick_device()
            # Nothing found; fall through and show the manual form.
            errors["base"] = "no_devices_found"

        # Manual entry fallback (shown when scan finds nothing or user re-scans).
        schema = vol.Schema(
            {
                vol.Optional(CONF_HOST, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 (scan path) — pick a discovered device
    # ------------------------------------------------------------------

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose one of the discovered frames."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_ip = user_input["device"]
            match = next(
                (d for d in self._discovered if d["ip"] == selected_ip), None
            )
            if match is None:
                errors["base"] = "unknown"
            else:
                self._selected_host = selected_ip
                self._selected_info = match["info"]
                return await self.async_step_name_device()

        device_options = {
            d["ip"]: "{} — firmware {}".format(
                d["ip"],
                d["info"].get("firmware_version", "unknown"),
            )
            for d in self._discovered
        }

        schema = vol.Schema(
            {vol.Required("device"): vol.In(device_options)}
        )

        return self.async_show_form(
            step_id="pick_device",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 3 (scan path) — enter a friendly name then create the entry
    # ------------------------------------------------------------------

    async def async_step_name_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a friendly name, then create the entry."""
        errors: dict[str, str] = {}

        # Use dimensions reported by the frame when available; fall back to picker.
        api_width: int | None = self._selected_info.get("width")
        api_height: int | None = self._selected_info.get("height")
        has_api_dims = isinstance(api_width, int) and isinstance(api_height, int)

        if user_input is not None:
            name = user_input[CONF_NAME].strip()

            if has_api_dims:
                width, height = api_width, api_height
            else:
                resolution = user_input.get(CONF_RESOLUTION, _DEFAULT_RESOLUTION)
                width, height = FRAME_RESOLUTIONS[resolution]

            unique_ip = (
                self._selected_info.get("wifi", {}).get("ip")
                or self._selected_info.get("ip_address")
                or self._selected_host
            )
            await self.async_set_unique_id(unique_ip)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_HOST: self._selected_host,
                    CONF_NAME: name,
                    CONF_WIDTH: width,
                    CONF_HEIGHT: height,
                },
            )

        if has_api_dims:
            # Dimensions come from the API — only ask for a name.
            schema = vol.Schema({vol.Required(CONF_NAME): str})
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_RESOLUTION, default=_DEFAULT_RESOLUTION): vol.In(
                        list(FRAME_RESOLUTIONS.keys())
                    ),
                }
            )

        return self.async_show_form(
            step_id="name_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": self._selected_host},
        )

    # ------------------------------------------------------------------
    # Options flow entry point
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler for this entry."""
        return FraimicOptionsFlow()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_local_ip(self) -> str:
        """Return the IPv4 address of the HA machine, falling back to 192.168.1.1."""
        try:
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:  # noqa: BLE001
            return "192.168.1.1"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class FraimicOptionsFlow(OptionsFlow):
    """Allow changing the frame name and scan interval after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_name: str = self.config_entry.data.get(CONF_NAME, "")
        current_interval: int = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current_name): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): vol.All(int, vol.Range(min=30)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
