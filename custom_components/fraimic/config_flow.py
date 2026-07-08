"""Config flow for the Fraimic integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE_KEY,
    CONF_HEIGHT,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_SIZE,
    CONF_WIDTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KIND_SCENES_HUB,
    CONF_ORIENTATION,
    ORIENTATION_AUTO,
    CONF_ROTATION_EDGE,
    EDGE_LEFT,
    EDGE_RIGHT,
    CONF_ROTATE_PORTRAIT_180,
    CONF_ROTATE_LANDSCAPE_180,
)
from .frame_types import FRAME_TYPES
from .helpers import (
    device_key_from_info,
    get_local_ip,
    mac_from_info,
    probe_device_size,
    probe_frame,
    scan_subnet,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

CONF_RESOLUTION = "resolution"
CONF_SCAN_INTERVAL = "scan_interval"
_DEFAULT_RESOLUTION = "13.3"


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
        self._detected_size: str | None = None

    # ------------------------------------------------------------------
    # Import — used internally (not user-facing) to auto-create the
    # device-less "scenes hub" config entry that hosts scene entities.
    # See scenes.py / scene.py for why scenes can't live on a frame's entry.
    # ------------------------------------------------------------------

    async def async_step_import(
        self, import_info: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle programmatic entry creation (currently: the scenes hub)."""
        if not import_info or import_info.get("kind") != KIND_SCENES_HUB:
            return self.async_abort(reason="not_implemented")

        await self.async_set_unique_id(f"{DOMAIN}_{KIND_SCENES_HUB}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Fraimic Scenes",
            data={"kind": KIND_SCENES_HUB},
        )

    # ------------------------------------------------------------------
    # DHCP discovery — called automatically when HA sees a DHCP lease
    # for a device whose MAC OUI matches our manifest filter.
    # ------------------------------------------------------------------

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> FlowResult:
        """Handle DHCP discovery: update existing entry's IP or offer new setup."""
        ip = discovery_info.ip

        info = await probe_frame(async_get_clientsession(self.hass), ip)

        if info is None:
            return self.async_abort(reason="not_fraimic_device")

        key = device_key_from_info(info)
        if not key:
            return self.async_abort(reason="not_fraimic_device")

        mac = mac_from_info(info)

        # Check every existing entry — match on device_key (new entries), MAC
        # (belt-and-braces), or — for entries created before 0.4.1 that don't
        # have a device_key/MAC yet (only backfilled lazily on the frame's
        # next successful coordinator poll) — fall back to matching on the
        # entry's currently configured host. Without this fallback, a DHCP
        # event arriving before that first poll completes (e.g. right after
        # upgrading and restarting) would fail to match any existing entry
        # and create a duplicate config entry for an already-configured frame.
        for entry in self._async_current_entries():
            entry_key = entry.data.get(CONF_DEVICE_KEY)
            entry_mac = entry.data.get(CONF_MAC, "")
            entry_host = entry.data.get(CONF_HOST)
            is_same_frame = (
                (entry_key and entry_key == key)
                or (mac and entry_mac and entry_mac == mac)
                or (not entry_key and not entry_mac and entry_host == ip)
            )
            if is_same_frame:
                # Same physical frame — update host if it moved, and/or
                # backfill the device_key/MAC fingerprint if this was a
                # legacy entry that didn't have one yet.
                if entry_host != ip or not entry_key or not entry_mac:
                    _LOGGER.info(
                        "Fraimic frame %s moved: %s → %s",
                        key,
                        entry_host,
                        ip,
                    )
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_HOST: ip,
                            CONF_DEVICE_KEY: key,
                            CONF_MAC: mac,
                        },
                    )
                return self.async_abort(reason="already_configured")

        # Genuinely new frame — start the normal setup flow.
        await self.async_set_unique_id(key)
        self._abort_if_unique_id_configured()
        return await self._async_use_device(ip, info)

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
                local_ip = await self.hass.async_add_executor_job(get_local_ip)
                self._discovered = await scan_subnet(
                    local_ip, async_get_clientsession(self.hass)
                )
                # Filter out already-configured frames.
                configured_keys = {
                    e.data.get(CONF_DEVICE_KEY)
                    for e in self._async_current_entries()
                    if e.data.get(CONF_DEVICE_KEY)
                }
                self._discovered = [
                    d for d in self._discovered
                    if device_key_from_info(d["info"]) not in configured_keys
                ]
                if self._discovered:
                    return await self.async_step_pick_device()
                errors["base"] = "no_devices_found"
            else:
                info = await probe_frame(async_get_clientsession(self.hass), host)

                if info is None:
                    errors[CONF_HOST] = "cannot_connect"
                else:
                    return await self._async_use_device(host, info)

        else:
            # First visit — auto-scan.
            local_ip = await self.hass.async_add_executor_job(get_local_ip)
            self._discovered = await scan_subnet(
                local_ip, async_get_clientsession(self.hass)
            )
            configured_keys = {
                e.data.get(CONF_DEVICE_KEY)
                for e in self._async_current_entries()
                if e.data.get(CONF_DEVICE_KEY)
            }
            self._discovered = [
                d for d in self._discovered
                if device_key_from_info(d["info"]) not in configured_keys
            ]
            if self._discovered:
                return await self.async_step_pick_device()
            errors["base"] = "no_devices_found"

        schema = vol.Schema({vol.Optional(CONF_HOST, default=""): str})
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
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
                return await self._async_use_device(selected_ip, match["info"])

        device_options = {
            d["ip"]: "{} — firmware {}".format(
                d["ip"],
                d["info"].get("firmware_version", "unknown"),
            )
            for d in self._discovered
        }

        schema = vol.Schema({vol.Required("device"): vol.In(device_options)})
        return self.async_show_form(
            step_id="pick_device", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Step 3 — name the device then create the entry
    # ------------------------------------------------------------------

    async def async_step_name_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a friendly name, then create the entry."""
        errors: dict[str, str] = {}

        api_width: int | None = self._selected_info.get("width")
        api_height: int | None = self._selected_info.get("height")
        has_api_dims = isinstance(api_width, int) and isinstance(api_height, int)

        # _async_use_device() already scraped this from the frame's own
        # /info admin page. When it succeeds there's no ambiguity to ask the
        # user to resolve -- the size dropdown below only appears as a
        # fallback for that detection failing (unrecognized/unreachable
        # /info page).
        detected_size = self._detected_size

        if user_input is not None:
            name = user_input[CONF_NAME].strip()

            size = detected_size or user_input.get(CONF_RESOLUTION, _DEFAULT_RESOLUTION)
            if has_api_dims:
                width, height = api_width, api_height
            else:
                width, height = FRAME_TYPES[size].resolution

            key = device_key_from_info(self._selected_info)
            mac = mac_from_info(self._selected_info)

            # Use device_key as the stable unique_id. Falls back to IP only
            # if the firmware is ancient enough not to return one.
            unique = key or (
                self._selected_info.get("wifi", {}).get("ip")
                or self._selected_host
            )
            await self.async_set_unique_id(unique)
            # If the same device was set up before at a different IP, update
            # the host in the existing entry instead of creating a duplicate.
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._selected_host}
            )

            return self.async_create_entry(
                title=name,
                data={
                    CONF_HOST: self._selected_host,
                    CONF_NAME: name,
                    CONF_WIDTH: width,
                    CONF_HEIGHT: height,
                    CONF_SIZE: size,
                    CONF_DEVICE_KEY: key or "",
                    CONF_MAC: mac,
                },
            )

        schema_fields: dict[Any, Any] = {vol.Required(CONF_NAME): str}
        if not detected_size:
            schema_fields[vol.Optional(CONF_RESOLUTION, default=_DEFAULT_RESOLUTION)] = vol.In(
                {key: ft.display_name for key, ft in FRAME_TYPES.items()}
            )
        schema = vol.Schema(schema_fields)

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

    async def _async_use_device(
        self, host: str, info: dict[str, Any]
    ) -> FlowResult:
        """Common continuation once a target frame's host + /api/info
        payload are known: best-effort auto-detect its physical size from
        /info's admin page (the JSON API doesn't expose size or resolution
        at all) before moving to naming, so setup only has to ask the user
        to pick a size when that detection fails."""
        self._selected_host = host
        self._selected_info = info

        self._detected_size = await probe_device_size(
            async_get_clientsession(self.hass), host
        )

        return await self.async_step_name_device()


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class FraimicOptionsFlow(OptionsFlow):
    """Allow changing the frame name, scan interval, and (for entries set up
    before physical size was tracked) backfilling the size after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Unlike name/scan_interval (stored as options), size belongs in
            # entry.data alongside width/height/host -- it's frame identity,
            # not a runtime preference.
            size = user_input.pop(CONF_RESOLUTION, "")
            if size:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_SIZE: size},
                )

            # The orientation lock isn't a field on this form (it's the
            # per-frame Orientation select entity), but async_create_entry
            # replaces options wholesale -- carry the stored value through so
            # saving this form doesn't silently reset the lock to Auto.
            orientation = self.config_entry.options.get(
                CONF_ORIENTATION, ORIENTATION_AUTO
            )
            if orientation != ORIENTATION_AUTO:
                user_input[CONF_ORIENTATION] = orientation

            return self.async_create_entry(title="", data=user_input)

        current_name: str = self.config_entry.data.get(CONF_NAME, "")
        current_interval: int = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_size: str | None = self.config_entry.data.get(CONF_SIZE)
        current_edge: str = self.config_entry.options.get(
            CONF_ROTATION_EDGE, EDGE_LEFT
        )
        current_rotate_portrait: bool = self.config_entry.options.get(
            CONF_ROTATE_PORTRAIT_180, False
        )
        current_rotate_landscape: bool = self.config_entry.options.get(
            CONF_ROTATE_LANDSCAPE_180, False
        )

        # Entries created before CONF_SIZE existed have no size on file --
        # rather than guess one (ambiguous once multiple panels share a
        # resolution), offer an explicit "leave unchanged" sentinel so this
        # field is never silently defaulted to a real size.
        size_options: dict[str, str] = (
            {} if current_size else {"": "Leave unset"}
        )
        size_options.update({key: ft.display_name for key, ft in FRAME_TYPES.items()})

        # Which panel edge points up when the frame is physically hung in its
        # non-native orientation. Official Fraimic frames hang one specific
        # way; clones can be mounted either way. Only matters when the
        # Orientation select entity locks the frame to its non-native
        # orientation -- if images then come out upside down, flip this.
        edge_options = {
            EDGE_LEFT: "Left edge up (Fraimic default)",
            EDGE_RIGHT: "Right edge up",
        }

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current_name): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): vol.All(int, vol.Range(min=30)),
                vol.Optional(
                    CONF_RESOLUTION, default=current_size or ""
                ): vol.In(size_options),
                vol.Optional(
                    CONF_ROTATION_EDGE, default=current_edge
                ): vol.In(edge_options),
                vol.Optional(
                    CONF_ROTATE_PORTRAIT_180, default=current_rotate_portrait
                ): bool,
                vol.Optional(
                    CONF_ROTATE_LANDSCAPE_180, default=current_rotate_landscape
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
