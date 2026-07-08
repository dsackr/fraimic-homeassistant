"""DataUpdateCoordinator for Fraimic frames."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_IMAGE,
    API_INFO,
    CONF_DEVICE_KEY,
    CONF_HOST,
    CONF_MAC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    CONF_WIDTH,
    CONF_HEIGHT,
)
from .helpers import (
    device_key_from_info,
    dimensions_from_info,
    find_frame_by_device_key,
    get_local_ip,
    mac_from_info,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# After this many consecutive poll failures, trigger a subnet rescan to find
# the frame at its new IP.
_FAILURES_BEFORE_RESCAN = 3

# Storage.Store (writes to .storage/, not entry.options) for the Frames panel
# thumbnail hint. One file per config entry, keyed on entry_id, so concurrent
# sends to different frames never race on the same file. Deliberately not
# entry.options -- that would trigger a full entry reload on every single
# send (see FraimicOrientationSelect for why that reload is fine there but
# not here).
_PREVIEW_STORE_VERSION = 1

# Same one-file-per-entry shape as the preview store above, but for a queued
# send awaiting delivery -- see async_send_image_or_queue.
_PENDING_STORE_VERSION = 1

# Schema stamp inside the pending payload itself (not the Store version, whose
# mismatch handling raises during load). Payloads written by v0.12.39/0.12.40
# have no stamp and are discarded on load: those versions could persist a
# stale-packed bin (see library.py's _migrate_stale_cache) and then redeliver
# it forever.
_PENDING_SCHEMA = 2

# While a send is queued, poll much more often than the user's configured
# scan_interval so a frame that wakes gets its image promptly instead of
# waiting up to the full (default 5 minute) interval. Fraimic frames have no
# documented wake-schedule/next-wake-time API to plan around instead -- the
# official REST API guide says a sleeping frame is "completely unreachable"
# until physically tapped -- so opportunistic polling is the only mechanism
# available.
_FAST_POLL_INTERVAL = timedelta(seconds=30)


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
        self._normal_update_interval = timedelta(seconds=scan_seconds)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=self._normal_update_interval,
        )

        self._consecutive_failures: int = 0
        self._rescan_in_progress: bool = False

        # Library image_id of the last successful send (Library "Send to
        # Canvas" or a Scene push -- both know the image_id up front). UI-only
        # preview hint for the Frames dashboard card; persisted via
        # _preview_store (see async_load_last_image/async_set_last_image)
        # rather than entry.options so it survives a restart without
        # triggering an entry reload on every send. Not set by the raw-upload
        # HTTP view or the send_image service, since those resolve a
        # media_content_id rather than a library image_id -- see
        # last_thumbnail below for how those paths still populate a preview.
        self.last_image_id: str | None = None

        # Small PNG preview of the last-sent image, for callers that have no
        # Library image_id to hand -- currently the generic send_image
        # service and the raw-upload card path, both of which resolve
        # something other than a Library-managed image (see
        # _handle_send_image in __init__.py and FraimicSendImageView in
        # http_api.py). Mutually exclusive with last_image_id: whichever send
        # path ran most recently clears the other, so the Frames panel never
        # shows a stale thumbnail from a different source. Also persisted via
        # _preview_store.
        self.last_thumbnail: bytes | None = None

        self._preview_store: Store = Store(
            hass, _PREVIEW_STORE_VERSION, f"{DOMAIN}_last_image_{config_entry.entry_id}"
        )

        # The newest image this frame hasn't confirmed receiving yet -- set
        # by async_send_image_or_queue when a send hits an unreachable
        # (sleeping) frame, and flushed by the poll loop once the frame
        # answers again. Exactly one entry, never a list: a later send always
        # overwrites an earlier still-pending one ("latest wins" -- confirmed
        # with the user, since a frame that slept through several sends
        # should end up showing the newest one, not flash through stale
        # intermediates). "token" lets _clear_pending_if_current tell a
        # slow in-flight send apart from a newer one that has since replaced
        # it, so a race can never wipe out the fresher entry.
        self.pending_send: dict[str, Any] | None = None
        self._pending_store: Store = Store(
            hass, _PENDING_STORE_VERSION, f"{DOMAIN}_pending_send_{config_entry.entry_id}"
        )
        self._flushing: bool = False

    async def async_load_last_image(self) -> None:
        """Hydrate last_image_id/last_thumbnail from disk. Call this once
        during setup, before the Frames panel can query /api/fraimic/frames,
        so the thumbnail survives a Home Assistant restart instead of
        dropping back to the generic icon until the next send."""
        try:
            data = await self._preview_store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to load cached frame preview for %s: %s", self.host, err)
            return
        if not data:
            return
        self.last_image_id = data.get("last_image_id")
        thumb_b64 = data.get("last_thumbnail_b64")
        if thumb_b64:
            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to decode cached frame preview for %s: %s", self.host, err
                )

    async def async_set_last_image(
        self, *, image_id: str | None = None, thumbnail: bytes | None = None
    ) -> None:
        """Record which image was last sent to this frame, for the Frames
        panel thumbnail, and persist it to disk so it survives a restart.
        Callers should pass exactly one of *image_id* / *thumbnail* -- the
        other is cleared, keeping last_image_id/last_thumbnail mutually
        exclusive (see their docstrings above)."""
        self.last_image_id = image_id
        self.last_thumbnail = thumbnail
        await self._preview_store.async_save(
            {
                "last_image_id": image_id,
                "last_thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
            }
        )

    # ------------------------------------------------------------------
    # Queued sends -- delivered once a sleeping frame answers again
    # ------------------------------------------------------------------

    async def async_load_pending_send(self) -> None:
        """Hydrate a queued-but-undelivered send from disk. Call this once
        during setup, before the first refresh, so a queued send survives a
        Home Assistant restart instead of being silently dropped."""
        try:
            data = await self._pending_store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to load pending send for %s: %s", self.host, err)
            return
        if not data:
            return
        if data.get("schema") != _PENDING_SCHEMA:
            # Written by a version without the schema stamp --
            # possibly a stale-packed bin caught in a redelivery loop. Drop it
            # rather than resume delivering a payload we can't trust.
            _LOGGER.warning(
                "Discarding queued send for %s persisted by an older version "
                "-- re-send the image if it's still wanted",
                self.host,
            )
            await self._pending_store.async_save(None)
            return
        self.pending_send = data
        self.update_interval = _FAST_POLL_INTERVAL

    async def _set_pending(self, payload: dict[str, Any]) -> None:
        self.pending_send = payload
        self.update_interval = _FAST_POLL_INTERVAL
        await self._pending_store.async_save(payload)
        self.async_update_listeners()

    async def _clear_pending_if_current(self, token: str) -> None:
        """Clear pending_send, but only if it's still the entry identified by
        *token* -- a newer send may have already replaced it while this one
        was in flight, and that newer entry must not be wiped out."""
        if self.pending_send is None or self.pending_send.get("token") != token:
            return
        self.pending_send = None
        self.update_interval = self._normal_update_interval
        await self._pending_store.async_save(None)
        self.async_update_listeners()

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        """Send *image_bytes* to the frame, or queue it for delivery once the
        frame wakes if it's currently unreachable.

        This is the entry point every send path (the send_image service, the
        raw-upload view, the library send view, and scene sends) should call
        instead of async_send_image directly, so queueing behaviour is
        applied uniformly regardless of where the image came from.
        """
        token = uuid.uuid4().hex
        payload: dict[str, Any] = {
            "schema": _PENDING_SCHEMA,
            "token": token,
            "bin_b64": base64.b64encode(image_bytes).decode("ascii"),
            "image_id": image_id,
            "thumbnail_b64": (
                base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
            ),
            "queued_at": time.time(),
        }
        # Recorded before the network call, not after: if Home Assistant
        # restarts mid-send, the queue must already know about this attempt
        # so it isn't lost.
        await self._set_pending(payload)

        self._flushing = True
        try:
            await self.async_send_image(image_bytes)
            await self._clear_pending_if_current(token)
        except (aiohttp.ClientConnectionError, TimeoutError):
            # Same failure pair _async_update_data treats as "frame is
            # unreachable, may be sleeping" -- leave it queued, the poll loop
            # will retry once the frame answers again.
            return {"success": False, "queued": True}
        finally:
            self._flushing = False

        await self.async_set_last_image(image_id=image_id, thumbnail=thumbnail)
        return {"success": True, "queued": False}

    async def _async_flush_pending_send(self) -> None:
        """Deliver the queued send now that a poll has succeeded. Guarded by
        _flushing so overlapping successful polls can't fire this twice.

        Exactly one delivery attempt: whether it succeeds or fails, the
        pending entry is dropped afterwards. We deliberately don't retry a
        failed flush -- on some clone firmwares the frame accepts the upload
        and blocks its HTTP response on the ~30s e-ink redraw until we time
        out, so a "failed" attempt may have actually displayed the image.
        Retrying that case would redraw the panel again with the same image,
        which is exactly the double-send this design avoids. A frame that is
        still genuinely offline gets another chance next time a *new* image
        is queued for it, not by re-attempting this one.
        """
        if self._flushing or self.pending_send is None:
            return
        self._flushing = True
        try:
            pending = self.pending_send
            image_bytes = base64.b64decode(pending["bin_b64"])
            try:
                await self.async_send_image(image_bytes)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Failed to deliver queued image to %s (%s) -- dropping it "
                    "rather than retrying, since a retry risks redrawing the "
                    "panel with an image it may have already received. "
                    "Re-send manually if it didn't arrive.",
                    self.host,
                    err,
                )
                await self._clear_pending_if_current(pending["token"])
                return
            await self._clear_pending_if_current(pending["token"])
            thumb_b64 = pending.get("thumbnail_b64")
            await self.async_set_last_image(
                image_id=pending.get("image_id"),
                thumbnail=base64.b64decode(thumb_b64) if thumb_b64 else None,
            )
            _LOGGER.info("Delivered queued image to frame %s", self.host)
        finally:
            self._flushing = False

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

            # The frame answered -- if something's queued, try to deliver it.
            # Checking "pending_send is not None" here (rather than tracking
            # a failure→success transition) is sufficient and idempotent: a
            # flush clears pending_send on success, so later successful
            # polls just no-op immediately, and it also covers the case
            # where the frame is already awake on the very first poll after
            # a Home Assistant restart with a queued send loaded from disk.
            if self.pending_send is not None and not self._flushing:
                self.hass.async_create_task(self._async_flush_pending_send())

            # Track the frame's reported native dimensions. entry.data
            # width/height are always the panel's own report -- the
            # orientation lock (entry.options, see helpers.render_spec_for_entry)
            # is applied at render time and never written back here, so the
            # two can't fight each other.
            dims = dimensions_from_info(data)
            if dims is not None:
                width, height = dims
                curr_w = self.config_entry.data.get(CONF_WIDTH)
                curr_h = self.config_entry.data.get(CONF_HEIGHT)
                if width != curr_w or height != curr_h:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_WIDTH: width, CONF_HEIGHT: height}
                    )
                    _LOGGER.info(
                        "Frame %s reported new dimensions: %dx%d",
                        self.host,
                        width,
                        height,
                    )

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
            local_ip = await self.hass.async_add_executor_job(get_local_ip)

            new_ip = await find_frame_by_device_key(
                local_ip, self.device_key, async_get_clientsession(self.hass)
            )
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
                # Generous on purpose: ESP32-based clone frames write the
                # ~190KB body to flash and then block on the ~30s e-ink
                # redraw BEFORE answering, so a 60s budget can expire after
                # the frame already accepted (and displayed) the image --
                # which used to read as a failure and requeue a duplicate.
                timeout=aiohttp.ClientTimeout(total=120),
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
