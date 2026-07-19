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
    CONF_DRIVER,
    CONF_HEIGHT,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_SIZE,
    CONF_WIDTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    DRIVER_MEURAL,
    DRIVER_SAMSUNG,
    KIND_SCENES_HUB,
    MEURAL_DEFAULT_HEIGHT,
    MEURAL_DEFAULT_WIDTH,
    MEURAL_SIZE_LABEL,
    SAMSUNG_DEFAULT_HEIGHT,
    SAMSUNG_DEFAULT_WIDTH,
    SAMSUNG_SIZE_LABEL,
    CONF_MDC_PIN,
    DEFAULT_MDC_PIN,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    ORIENTATION_AUTO,
    CONF_ROTATION_EDGE,
    EDGE_LEFT,
    EDGE_RIGHT,
    CONF_ROTATE_PORTRAIT_180,
    CONF_ROTATE_LANDSCAPE_180,
)
from .frame_types import FRAME_TYPES
from .helpers import (
    detect_frame_type_from_info,
    device_key_from_info,
    dimensions_from_info,
    get_local_ip,
    mac_from_info,
    match_and_update_entry,
    probe_device_size,
    probe_frame,
    scan_subnet,
)
from .meural import probe_meural

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

CONF_RESOLUTION = "resolution"
CONF_SCAN_INTERVAL = "scan_interval"
_DEFAULT_RESOLUTION = "13.3"
# Sentinel option in the pick_device list: frames on another subnet/VLAN
# never appear in the scan, and a successful scan used to make the manual
# host field unreachable entirely.
_MANUAL_DEVICE = "__manual__"


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
            title="Digital Frames Scenes",
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

        # Same physical frame as an existing entry? match_and_update_entry
        # also refreshes the host if the frame moved and backfills the
        # device_key/MAC fingerprint on legacy entries.
        matched = match_and_update_entry(
            self.hass, list(self._async_current_entries()), ip, info
        )
        if matched is not None:
            return self.async_abort(reason="already_configured")

        # Genuinely new frame — start the normal setup flow. The title
        # placeholder keeps DHCP-discovered cards visually identical to the
        # periodic scan's ("Fraimic Frame (<ip>)" instead of bare "Fraimic").
        await self.async_set_unique_id(key)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": ip}
        return await self._async_use_device(ip, info)

    # ------------------------------------------------------------------
    # Integration discovery — started by discovery.py's periodic subnet
    # scan for each frame that isn't configured yet. Parking on the naming
    # form below is what feeds HA's "Discovered" card + notification.
    # ------------------------------------------------------------------

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Handle a frame found by the periodic background subnet scan."""
        ip: str = discovery_info["ip"]
        info: dict[str, Any] = discovery_info["info"]

        key = device_key_from_info(info)
        if not key:
            return self.async_abort(reason="not_fraimic_device")

        # raise_on_progress (the default) aborts this flow if a discovery
        # flow for the same frame is already pending — that's the whole
        # dedup story across 20-minute rescans. The scan already filters
        # out configured frames, but _abort_if_unique_id_configured guards
        # the race where one was added between scan and flow start.
        await self.async_set_unique_id(key)
        self._abort_if_unique_id_configured(updates={CONF_HOST: ip})

        self.context["title_placeholders"] = {"name": ip}
        return await self._async_use_device(ip, info)

    # ------------------------------------------------------------------
    # Step 1 — choose driver (Fraimic Spectra family vs Meural local)
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Primary entry: pick Fraimic/clone or Meural Canvas (local)."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["add_fraimic", "add_meural", "add_samsung"],
        )

    # ------------------------------------------------------------------
    # Fraimic / API-compatible clone — scan or manual IP
    # ------------------------------------------------------------------

    async def async_step_add_fraimic(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Auto-scan for Fraimic frames; fall back to manual IP."""
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
            step_id="add_fraimic", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Meural Canvas (local LAN postcard) — FramePort Phase 3
    # ------------------------------------------------------------------

    async def async_step_add_meural(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a Meural Canvas by local IP (no Meural cloud account)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            name = (user_input.get(CONF_NAME) or "").strip() or f"Meural {host}"
            width = int(user_input.get(CONF_WIDTH) or MEURAL_DEFAULT_WIDTH)
            height = int(user_input.get(CONF_HEIGHT) or MEURAL_DEFAULT_HEIGHT)

            info = await probe_meural(async_get_clientsession(self.hass), host)
            if info is None:
                errors[CONF_HOST] = "cannot_connect"
            else:
                unique = f"meural:{host}"
                # Prefer a stable serial from identify payload when present.
                for key in ("serial", "serialNumber", "deviceId", "id", "mac"):
                    if info.get(key):
                        unique = f"meural:{info[key]}"
                        break
                await self.async_set_unique_id(str(unique))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                # Seed follow-device orientation from gsensor so crop/send
                # match hang immediately (see MeuralCoordinator follow).
                from .meural import meural_orientation_from_payload  # noqa: PLC0415

                options: dict[str, Any] = {CONF_ORIENTATION_FOLLOW_DEVICE: True}
                device_orient = meural_orientation_from_payload(info)
                if device_orient:
                    options[CONF_ORIENTATION] = device_orient

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_DRIVER: DRIVER_MEURAL,
                        CONF_HOST: host,
                        CONF_NAME: name,
                        CONF_WIDTH: width,
                        CONF_HEIGHT: height,
                        CONF_SIZE: MEURAL_SIZE_LABEL,
                        CONF_DEVICE_KEY: str(unique),
                        CONF_MAC: "",
                    },
                    options=options,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME, default=""): str,
                vol.Optional(CONF_WIDTH, default=MEURAL_DEFAULT_WIDTH): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=8000)
                ),
                vol.Optional(CONF_HEIGHT, default=MEURAL_DEFAULT_HEIGHT): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=8000)
                ),
            }
        )
        return self.async_show_form(
            step_id="add_meural", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Samsung EM32DX (local MDC — experimental, protocol from fayep/Joyous)
    # ------------------------------------------------------------------

    async def async_step_add_samsung(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a Samsung E-Paper frame by LAN IP + MDC PIN (no cloud)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            name = (user_input.get(CONF_NAME) or "").strip() or f"Samsung {host}"
            width = int(user_input.get(CONF_WIDTH) or SAMSUNG_DEFAULT_WIDTH)
            height = int(user_input.get(CONF_HEIGHT) or SAMSUNG_DEFAULT_HEIGHT)
            pin = str(user_input.get(CONF_MDC_PIN) or DEFAULT_MDC_PIN).strip()
            mac = str(user_input.get(CONF_MAC) or "").strip()

            if not host:
                errors[CONF_HOST] = "cannot_connect"
            else:
                unique = f"samsung:{host}"
                if mac:
                    unique = f"samsung:{mac.replace(':', '').lower()}"
                await self.async_set_unique_id(str(unique))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_DRIVER: DRIVER_SAMSUNG,
                        CONF_HOST: host,
                        CONF_NAME: name,
                        CONF_WIDTH: width,
                        CONF_HEIGHT: height,
                        CONF_SIZE: SAMSUNG_SIZE_LABEL,
                        CONF_DEVICE_KEY: str(unique),
                        CONF_MAC: mac,
                        CONF_MDC_PIN: pin or DEFAULT_MDC_PIN,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME, default=""): str,
                vol.Optional(CONF_MDC_PIN, default=DEFAULT_MDC_PIN): str,
                vol.Optional(CONF_MAC, default=""): str,
                vol.Optional(CONF_WIDTH, default=SAMSUNG_DEFAULT_WIDTH): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=8000)
                ),
                vol.Optional(CONF_HEIGHT, default=SAMSUNG_DEFAULT_HEIGHT): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=8000)
                ),
            }
        )
        return self.async_show_form(
            step_id="add_samsung", data_schema=schema, errors=errors
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
            if selected_ip == _MANUAL_DEVICE:
                return await self.async_step_manual()
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
        device_options[_MANUAL_DEVICE] = "Enter an IP address manually…"

        schema = vol.Schema({vol.Required("device"): vol.In(device_options)})
        return self.async_show_form(
            step_id="pick_device", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Step 2b — manual IP entry (escape hatch from the picker, for frames
    # the subnet scan can't see)
    # ------------------------------------------------------------------

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a frame by IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            info = await probe_frame(async_get_clientsession(self.hass), host)
            if info is None:
                errors[CONF_HOST] = "cannot_connect"
            else:
                return await self._async_use_device(host, info)

        schema = vol.Schema({vol.Required(CONF_HOST): str})
        return self.async_show_form(
            step_id="manual", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Step 3 — name the device then create the entry
    # ------------------------------------------------------------------

    async def async_step_name_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a friendly name, then create the entry."""
        errors: dict[str, str] = {}

        api_dims = dimensions_from_info(self._selected_info)

        # _async_use_device() already scraped this from the frame's own
        # /info admin page. When it succeeds there's no ambiguity to ask the
        # user to resolve -- the size dropdown below only appears as a
        # fallback for that detection failing (unrecognized/unreachable
        # /info page).
        detected_size = self._detected_size

        if user_input is not None:
            name = user_input[CONF_NAME].strip()

            size = detected_size or user_input.get(CONF_RESOLUTION, _DEFAULT_RESOLUTION)
            if api_dims is not None:
                width, height = api_dims
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

        # Two-line detection: the /info HTML scrape is authoritative when it
        # works (official firmware), and the /api/info resolution lookup
        # covers clones whose firmware doesn't serve that page -- the size
        # dropdown in name_device only appears when both come up empty.
        self._detected_size = await probe_device_size(
            async_get_clientsession(self.hass), host
        ) or detect_frame_type_from_info(info)

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

        # No name field here: renaming goes through config_entries/update
        # (entry.title), driven by the panel's frame-settings menu. The old
        # CONF_NAME option was written but never read (CODE_REVIEW #14).
        schema = vol.Schema(
            {
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
