"""The Fraimic integration."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    CONF_HEIGHT,
    CONF_WIDTH,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import FraimicCoordinator
from .http_api import FraimicSendImageView

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service schema definitions
# ---------------------------------------------------------------------------

_DEVICE_ID_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
    }
)

_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("media_content_id"): cv.string,
    }
)


# ---------------------------------------------------------------------------
# Domain-level setup (runs once when the domain is first loaded)
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the card JS static path, HTTP view, and frontend injection."""
    card_path = hass.config.path("custom_components/fraimic/fraimic-card.js")

    # Serve the Lovelace card JS at a stable URL.
    hass.http.register_static_path(
        "/fraimic/fraimic-card.js",
        card_path,
        cache_headers=False,
    )

    # Register the image-upload HTTP endpoint.
    hass.http.register_view(FraimicSendImageView())

    # Inject the card into the HA frontend so it's always available.
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

    add_extra_js_url(hass, "/fraimic/fraimic-card.js")

    return True


# ---------------------------------------------------------------------------
# Integration setup / teardown (per config entry)
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: "ConfigEntry") -> bool:
    """Set up a Fraimic frame from a config entry."""

    coordinator = FraimicCoordinator(hass, entry)

    # Perform the first data fetch; raises ConfigEntryNotReady on failure so
    # HA will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (only for the first entry; subsequent entries
    # reuse the same service handlers).
    if not hass.services.has_service(DOMAIN, "send_image"):
        _register_services(hass)

    # Re-register listener so option changes (e.g. scan_interval) take effect.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: "ConfigEntry") -> bool:
    """Unload a Fraimic config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove the top-level domain dict when no entries remain.
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

            # Remove services when the last entry is gone.
            for service in ("send_image", "refresh", "sleep", "restart"):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: "ConfigEntry") -> None:
    """Handle config entry option updates (e.g. scan_interval changes)."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def _get_coordinator_by_device_id(
    hass: HomeAssistant, device_id: str
) -> tuple[FraimicCoordinator, str]:
    """Return (coordinator, entry_id) for the given device_id, or raise."""
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)
    if device_entry is None:
        raise HomeAssistantError(f"Device '{device_id}' not found in device registry")

    domain_data: dict[str, FraimicCoordinator] = hass.data.get(DOMAIN, {})
    for entry_id in device_entry.config_entries:
        if entry_id in domain_data:
            return domain_data[entry_id], entry_id

    raise HomeAssistantError(
        f"No Fraimic coordinator found for device '{device_id}'"
    )


async def _resolve_media_path(hass: HomeAssistant, media_content_id: str) -> str:
    """Resolve a media content_id or path string to an absolute filesystem path."""
    if media_content_id.startswith("media-source://"):
        try:
            from homeassistant.components.media_source import (  # noqa: PLC0415
                async_resolve_media,
            )

            media_item = await async_resolve_media(hass, media_content_id, None)
            url: str = media_item.url

            prefix = "/media/local/"
            if url.startswith(prefix):
                local_dir = hass.config.media_dirs.get(
                    "local", hass.config.path("media")
                )
                return os.path.join(local_dir, url[len(prefix):])

            raise HomeAssistantError(f"Cannot access non-local media URL: {url}")
        except ImportError as err:
            raise HomeAssistantError(
                "media_source component is not available"
            ) from err

    if media_content_id.startswith("/media/"):
        local_dir = hass.config.media_dirs.get("local", hass.config.path("media"))
        return os.path.join(local_dir, media_content_id[len("/media/"):])

    return media_content_id


def _register_services(hass: HomeAssistant) -> None:
    """Register all Fraimic services."""

    async def _handle_restart(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_RESTART)
        _LOGGER.info("Restart command sent to frame %s", coordinator.host)

    async def _handle_sleep(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_SLEEP)
        _LOGGER.info("Sleep command sent to frame %s", coordinator.host)

    async def _handle_refresh(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_REFRESH)
        _LOGGER.info("Refresh command sent to frame %s", coordinator.host)

    async def _handle_send_image(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        media_content_id: str = call.data["media_content_id"]

        coordinator, entry_id = _get_coordinator_by_device_id(hass, device_id)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")

        width: int = entry.data[CONF_WIDTH]
        height: int = entry.data[CONF_HEIGHT]

        abs_path = await _resolve_media_path(hass, media_content_id)

        if not os.path.isfile(abs_path):
            raise HomeAssistantError(f"Media file not found: {abs_path}")

        from .image_converter import convert_image  # noqa: PLC0415

        try:
            image_bytes: bytes = await hass.async_add_executor_job(
                convert_image, abs_path, width, height
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"Failed to convert image '{abs_path}': {err}"
            ) from err

        await coordinator.async_send_image(image_bytes)
        _LOGGER.info(
            "Image '%s' (%dx%d) sent to frame %s",
            abs_path,
            width,
            height,
            coordinator.host,
        )

    hass.services.async_register(
        DOMAIN, "restart", _handle_restart, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "sleep", _handle_sleep, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "refresh", _handle_refresh, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "send_image", _handle_send_image, schema=_SEND_IMAGE_SCHEMA
    )
