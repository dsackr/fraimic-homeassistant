"""Periodic background discovery of Fraimic frames on the local network.

DHCP discovery (config_flow.async_step_dhcp) only fires when HA happens to
observe a live DHCP handshake from a matching MAC OUI — a frame with an
existing lease, or a Wi-Fi module from an unlisted OUI batch, never triggers
it. This module closes that gap: a recurring subnet sweep that feeds every
genuinely new frame into HA's standard discovery pipeline
(SOURCE_INTEGRATION_DISCOVERY), so it surfaces on the Settings → Devices &
Services "Discovered" card and the "new devices discovered" notification
exactly like any other discoverable integration.

Registered from async_setup (domain-level, alongside the scenes-hub entry),
so discovery works from the very first restart after install — before any
frame is configured.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, KIND_SCENES_HUB
from .helpers import (
    device_key_from_info,
    get_local_ip,
    match_and_update_entry,
    scan_subnet,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=20)


@callback
def async_setup_discovery(hass: "HomeAssistant") -> None:
    """Register the periodic background scan (idempotent)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_discovery_unsub" in domain_data:
        return

    # Skip-if-running rather than queue: a sweep that fires while the
    # previous one is still probing has nothing new to add.
    scan_lock = asyncio.Lock()

    async def _async_scan(_now=None) -> None:
        if scan_lock.locked():
            return
        async with scan_lock:
            try:
                await _async_scan_once(hass)
            except Exception:  # noqa: BLE001
                # A failed sweep must never kill the timer — the next
                # interval retries from scratch.
                _LOGGER.exception("Fraimic background discovery scan failed")

    unsubs: list = []

    # First sweep as soon as HA is fully started (or immediately if the
    # integration loaded into an already-running instance, e.g. via a
    # reload), so a new install doesn't wait a full interval for its
    # first discovery.
    if hass.is_running:
        hass.async_create_task(_async_scan())
    else:

        async def _on_started(_event) -> None:
            await _async_scan()

        unsubs.append(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
        )

    unsubs.append(async_track_time_interval(hass, _async_scan, SCAN_INTERVAL))

    @callback
    def _on_stop(_event) -> None:
        for unsub in domain_data.pop("_discovery_unsub", []):
            unsub()

    unsubs.append(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    domain_data["_discovery_unsub"] = unsubs

    # Exposed for the on-demand rescan endpoint below: frames sleep, so a
    # single boot-time sweep goes stale fast -- the panel re-runs the sweep
    # whenever it opens, keeping its discovery banner current.
    domain_data["_discovery_scan"] = _async_scan
    hass.http.register_view(FraimicDiscoveryScanView())


class FraimicDiscoveryScanView(HomeAssistantView):
    """POST /api/digital_frames/discovery/scan — run one discovery sweep now."""

    url = "/api/digital_frames/discovery/scan"
    name = "api:digital_frames:discovery:scan"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        # The sweep starts config flows, an admin-only capability -- mirror
        # that here rather than letting any authenticated user trigger it.
        if not request["hass_user"].is_admin:
            return self.json_message("Admin required", status_code=403)
        scan = hass.data.get(DOMAIN, {}).get("_discovery_scan")
        if scan is None:
            return self.json_message("Discovery not initialised", status_code=500)
        await scan()
        return self.json({"success": True})


async def _async_scan_once(hass: "HomeAssistant") -> None:
    """One subnet sweep: update moved frames, start flows for new ones."""
    local_ip = await hass.async_add_executor_job(get_local_ip)
    found = await scan_subnet(local_ip, async_get_clientsession(hass))
    if not found:
        return

    frame_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("kind") != KIND_SCENES_HUB
    ]

    for item in found:
        ip, info = item["ip"], item["info"]
        key = device_key_from_info(info)
        if not key:
            continue
        try:
            # Configured frame (host refreshed in place if it moved)?
            if match_and_update_entry(hass, frame_entries, ip, info) is not None:
                continue

            _LOGGER.info(
                "Discovered new Fraimic frame at %s (device_key=%s)", ip, key
            )
            # Feeds HA's discovery pipeline; a flow already pending for
            # this device_key aborts itself via async_set_unique_id's
            # raise_on_progress, so rescans never stack duplicates.
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={"ip": ip, "info": info},
            )
        except Exception:  # noqa: BLE001
            # One bad frame (e.g. it went to sleep mid-probe) must not
            # kill the rest of the sweep.
            _LOGGER.exception("Failed to process discovered frame at %s", ip)
