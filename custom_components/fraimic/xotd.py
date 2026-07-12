"""xOTD (day-of-the-day content): many independent instances, each pairing
one content mode (joke/quote/scripture/image) with one target frame and its
own schedule -- e.g. Joke of the Day hourly on one frame and Scripture of
the Day daily on another, running simultaneously.

Modeled on ScheduleManager (schedules.py), not ScenePackManager: this is a
CRUD-over-many-independent-records problem (arbitrary instance_id keys),
not a one-row-per-catalog-id problem.

Two execution paths, dispatched by content_mode at fire time:
  - joke/quote/scripture ("text" modes): the frame-addons "xotd" pack's
    script is downloaded fresh into this instance's own directory and run
    as a subprocess, exactly like ScenePackManager's widget execution --
    just keyed by a generated instance_id instead of a shared pack_id, so
    N instances of the same content mode can run independently.
  - image: no script, no subprocess. A web feed (NASA APOD / Wikimedia
    Picture of the Day / Bing daily wallpaper) is fetched directly and
    imported into the photo library tagged "Image of the Day", or an
    existing photo is picked at random from a user-chosen album -- either
    way the result is sent to the frame via SceneManager.async_send_mappings,
    the same single executor every other send path in the integration
    terminates in. This mode needs direct, in-process access to the photo
    library, so handing it to an external script would mean minting it an
    HA auth token; reusing the pipeline already used for wall/scene sends
    avoids that entirely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shutil
import sys
import urllib.parse
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, DOMAIN, SCENE_PACK_RAW_BASE
from .frame_types import byte_layout_for_resolution
from .helpers import render_spec_for_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .library import LibraryManager
    from .scene_packs import ScenePackManager

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}_xotd"
_STORAGE_VERSION = 1

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

_CONTENT_MODES = ("joke", "quote", "scripture", "word", "image")
_IMAGE_SUB_MODES = ("image_feed", "image_album")
_IMAGE_FEED_PROVIDERS = ("nasa_apod", "wikimedia_potd", "bing_wallpaper")
_IMAGE_OTD_ALBUM = "Image of the Day"


class XotdError(Exception):
    """Raised for invalid xOTD instance operations (bad shape, not found)."""


def _parse_hms(value: Any) -> tuple[int, int, int]:
    """Same defensive HH:MM:SS parsing scene_packs.py's _schedule_widget
    uses for daily widgets -- an unparseable time falls back to 7:00 AM
    rather than raising, since this also runs at arm time (startup)."""
    try:
        parts = [int(p) for p in str(value).split(":")]
        hour = parts[0]
        minute = parts[1] if len(parts) > 1 else 0
        second = parts[2] if len(parts) > 2 else 0
    except (TypeError, ValueError, IndexError):
        return 7, 0, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return 7, 0, 0
    return hour, minute, second


def _validate_schedule(schedule: Any) -> dict[str, Any]:
    if not isinstance(schedule, dict):
        raise XotdError("Schedule must be an object")
    stype = schedule.get("type")
    if stype == "daily":
        hour, minute, second = _parse_hms(schedule.get("time", "07:00:00"))
        return {"type": "daily", "time": f"{hour:02d}:{minute:02d}:{second:02d}"}
    if stype == "hourly":
        return {"type": "hourly"}
    raise XotdError(f"Invalid schedule type: {stype!r} (expected 'hourly' or 'daily')")


def _validate_mode_config(content_mode: str, mode_config: Any) -> dict[str, Any]:
    """Text modes (joke/quote/scripture) accept whatever the xotd catalog
    pack's own config_schema collected -- validated generically by the
    panel's schema-driven form, not re-validated field-by-field here.
    Image mode's fields have no catalog backing, so they're validated
    explicitly."""
    mode_config = dict(mode_config) if isinstance(mode_config, dict) else {}
    if content_mode != "image":
        return mode_config

    sub_mode = mode_config.get("sub_mode")
    if sub_mode not in _IMAGE_SUB_MODES:
        raise XotdError(f"Invalid image sub_mode: {sub_mode!r} (expected 'image_feed' or 'image_album')")
    if sub_mode == "image_feed":
        provider = mode_config.get("feed_provider")
        if provider not in _IMAGE_FEED_PROVIDERS:
            raise XotdError(f"Invalid feed_provider: {provider!r}")
    else:  # image_album
        if not mode_config.get("album"):
            raise XotdError("image_album mode needs an album")
    return mode_config


class XotdInstance:
    """One (content_mode, frame, schedule, mode_config) pairing. Plain
    dict-backed record, same style as schedules.py's Schedule."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.instance_id: str = data["instance_id"]
        self.content_mode: str = data["content_mode"]
        self.frame_id: str = data["frame_id"]
        self.schedule: dict[str, Any] = dict(data.get("schedule") or {"type": "hourly"})
        self.mode_config: dict[str, Any] = dict(data.get("mode_config") or {})
        self.enabled: bool = bool(data.get("enabled", True))
        self.created_at: str = data.get("created_at") or dt_util.now().isoformat()
        self.last_run_at: str | None = data.get("last_run_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "content_mode": self.content_mode,
            "frame_id": self.frame_id,
            "schedule": self.schedule,
            "mode_config": self.mode_config,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
        }


class XotdManager:
    """Owns the set of xOTD instances and their armed HA timers."""

    def __init__(
        self,
        hass: "HomeAssistant",
        library: "LibraryManager",
        scene_packs: "ScenePackManager",
    ) -> None:
        self.hass = hass
        self._library = library
        self._scene_packs = scene_packs
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._instances: dict[str, XotdInstance] = {}
        # instance_id -> timer unsubscribe. Same lifecycle discipline as
        # ScenePackManager._schedulers / ScheduleManager._schedulers: cancel
        # per-instance on edit/delete, all-at-once in unload().
        self._schedulers: dict[str, Any] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        for data in (stored or {}).get("instances", []):
            try:
                instance = XotdInstance(data)
            except KeyError:
                _LOGGER.warning("Dropping malformed stored xOTD instance: %s", data)
                continue
            self._instances[instance.instance_id] = instance

        for instance in self._instances.values():
            self._arm(instance)

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"instances": [i.to_dict() for i in self._instances.values()]}
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def async_list_instances(self) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self._instances.values()]

    async def async_get_instance(self, instance_id: str) -> dict[str, Any] | None:
        instance = self._instances.get(instance_id)
        return instance.to_dict() if instance is not None else None

    def _validate_frame(self, frame_id: Any) -> None:
        entry = self.hass.config_entries.async_get_entry(frame_id) if frame_id else None
        if entry is None or entry.domain != DOMAIN:
            raise XotdError("Selected target frame was not found")

    async def async_create_instance(
        self,
        content_mode: Any,
        frame_id: Any,
        schedule: Any,
        mode_config: Any,
        enabled: bool = True,
    ) -> dict[str, Any]:
        if content_mode not in _CONTENT_MODES:
            raise XotdError(f"Invalid content_mode: {content_mode!r}")
        self._validate_frame(frame_id)
        schedule = _validate_schedule(schedule)
        mode_config = _validate_mode_config(content_mode, mode_config)

        instance = XotdInstance(
            {
                "instance_id": uuid.uuid4().hex[:12],
                "content_mode": content_mode,
                "frame_id": frame_id,
                "schedule": schedule,
                "mode_config": mode_config,
                "enabled": bool(enabled),
                "created_at": dt_util.now().isoformat(),
            }
        )
        self._instances[instance.instance_id] = instance
        self._arm(instance)
        await self._async_persist()
        return instance.to_dict()

    async def async_update_instance(
        self, instance_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        instance = self._instances.get(instance_id)
        if instance is None:
            raise XotdError(f"Instance '{instance_id}' not found")

        content_mode = changes.get("content_mode", instance.content_mode)
        if content_mode not in _CONTENT_MODES:
            raise XotdError(f"Invalid content_mode: {content_mode!r}")

        if "frame_id" in changes:
            self._validate_frame(changes["frame_id"])
            instance.frame_id = changes["frame_id"]
        if "schedule" in changes:
            instance.schedule = _validate_schedule(changes["schedule"])
        if "mode_config" in changes or "content_mode" in changes:
            instance.mode_config = _validate_mode_config(
                content_mode, changes.get("mode_config", instance.mode_config)
            )
        instance.content_mode = content_mode
        if "enabled" in changes:
            instance.enabled = bool(changes["enabled"])

        self._arm(instance)
        await self._async_persist()
        return instance.to_dict()

    async def async_delete_instance(self, instance_id: str) -> None:
        instance = self._instances.get(instance_id)
        if instance is None:
            raise XotdError(f"Instance '{instance_id}' not found")

        self._disarm(instance_id)
        if instance.content_mode != "image":
            addon_dir = self.hass.config.path("fraimic_addons", f"xotd_{instance_id}")
            if os.path.exists(addon_dir):
                await self.hass.async_add_executor_job(shutil.rmtree, addon_dir)

        del self._instances[instance_id]
        await self._async_persist()

    # ------------------------------------------------------------------
    # Arming / firing
    # ------------------------------------------------------------------

    def _arm(self, instance: XotdInstance) -> None:
        self._disarm(instance.instance_id)
        if not instance.enabled:
            return

        instance_id = instance.instance_id

        async def run_job(*_args: Any) -> None:
            # Re-fetch: the record may have been edited/deleted since arming.
            current = self._instances.get(instance_id)
            if current is None or not current.enabled:
                return
            await self._async_fire(current)

        schedule = instance.schedule
        if schedule.get("type") == "daily":
            hour, minute, second = _parse_hms(schedule.get("time", "07:00:00"))
            self._schedulers[instance_id] = async_track_time_change(
                self.hass, run_job, hour=hour, minute=minute, second=second
            )
        else:
            self._schedulers[instance_id] = async_track_time_interval(
                self.hass, run_job, timedelta(hours=1)
            )

    def _disarm(self, instance_id: str) -> None:
        unsub = self._schedulers.pop(instance_id, None)
        if unsub is not None:
            unsub()

    def unload(self) -> None:
        """Cancel every armed timer."""
        for instance_id in list(self._schedulers):
            self._disarm(instance_id)

    async def _async_fire(self, instance: XotdInstance) -> None:
        instance.last_run_at = dt_util.now().isoformat()
        await self._async_persist()
        try:
            if instance.content_mode == "image":
                await self._async_run_image_instance(instance)
            else:
                await self._async_run_text_instance(instance)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xOTD instance '%s' (%s) failed to run: %s",
                instance.instance_id,
                instance.content_mode,
                err,
            )

    # ------------------------------------------------------------------
    # Text modes (joke/quote/scripture): download + subprocess, same
    # contract as ScenePackManager's widget execution, just keyed by a
    # generated instance_id instead of the shared "xotd" pack_id so N
    # instances can run independently.
    # ------------------------------------------------------------------

    async def _async_run_text_instance(self, instance: XotdInstance) -> None:
        pack = await self._scene_packs.async_get_pack("xotd")
        script_url = f"{SCENE_PACK_RAW_BASE}/{pack.get('script_url')}"
        session = async_get_clientsession(self.hass)

        try:
            async with session.get(script_url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.error(
                        "xOTD instance '%s': HTTP %s fetching script",
                        instance.instance_id, resp.status,
                    )
                    return
                script_content = await resp.read()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xOTD instance '%s': failed to fetch script: %s", instance.instance_id, err
            )
            return

        addon_dir = self.hass.config.path("fraimic_addons", f"xotd_{instance.instance_id}")
        await self.hass.async_add_executor_job(os.makedirs, addon_dir, True)
        script_path = os.path.join(addon_dir, "renderer.py")

        def _write_script() -> None:
            with open(script_path, "wb") as f:
                f.write(script_content)

        await self.hass.async_add_executor_job(_write_script)

        entry = self.hass.config_entries.async_get_entry(instance.frame_id)
        if entry is None:
            _LOGGER.error(
                "xOTD instance '%s': target frame no longer exists", instance.instance_id
            )
            return

        spec = render_spec_for_entry(entry)
        try:
            layout = byte_layout_for_resolution(spec.width, spec.height)
        except Exception:  # noqa: BLE001
            layout = "split_half"

        script_config: dict[str, Any] = {
            "frame": {
                "ip_address": entry.data.get(CONF_HOST),
                "resolution": [spec.width, spec.height],
                "layout": layout,
            },
            "timezone": self.hass.config.time_zone or "UTC",
            "content_mode": instance.content_mode,
        }
        for field in pack.get("config_schema", []):
            name = field["name"]
            if name == "content_mode":
                continue
            val = instance.mode_config.get(name)
            if field.get("type") == "json" and val:
                try:
                    val = json.loads(val)
                except (TypeError, ValueError):
                    val = None
            if val is not None:
                script_config[name] = val

        config_path = os.path.join(addon_dir, "config.json")

        def _write_config() -> None:
            with open(config_path, "w") as f:
                json.dump(script_config, f, indent=2)

        await self.hass.async_add_executor_job(_write_config)

        _LOGGER.info("Executing xOTD instance script: %s", script_path)
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=addon_dir,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                _LOGGER.error(
                    "xOTD instance '%s' run failed (exit code %d):\n%s",
                    instance.instance_id, process.returncode, stderr.decode().strip(),
                )
            else:
                _LOGGER.info(
                    "xOTD instance '%s' completed: %s",
                    instance.instance_id, stdout.decode().strip(),
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to execute xOTD instance '%s': %s", instance.instance_id, err)

    # ------------------------------------------------------------------
    # Image mode: no script/subprocess -- runs entirely in-process, either
    # importing a freshly-fetched web-feed image into the library (tagged
    # into the fixed "Image of the Day" album) or picking an existing image
    # at random from a user-chosen album, then sending it via the same
    # SceneManager.async_send_mappings every other send path uses.
    # ------------------------------------------------------------------

    async def _async_send_image_to_frame(self, instance: XotdInstance, image_id: str) -> None:
        scene_manager = self.hass.data.get(DOMAIN, {}).get("_scenes")
        if scene_manager is None:
            _LOGGER.error(
                "xOTD instance '%s': scene manager not available", instance.instance_id
            )
            return
        try:
            await scene_manager.async_send_mappings(self.hass, {instance.frame_id: image_id})
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xOTD instance '%s': failed to send image: %s", instance.instance_id, err
            )

    async def _async_run_image_instance(self, instance: XotdInstance) -> None:
        sub_mode = instance.mode_config.get("sub_mode")
        if sub_mode == "image_feed":
            await self._async_run_image_feed(instance)
        elif sub_mode == "image_album":
            await self._async_run_image_album(instance)
        else:
            _LOGGER.error(
                "xOTD instance '%s': invalid image sub_mode %r",
                instance.instance_id, sub_mode,
            )

    async def _async_run_image_feed(self, instance: XotdInstance) -> None:
        provider = instance.mode_config.get("feed_provider")
        session = async_get_clientsession(self.hass)
        today = dt_util.now()

        try:
            if provider == "nasa_apod":
                api_key = instance.mode_config.get("nasa_api_key") or "DEMO_KEY"
                async with session.get(
                    "https://api.nasa.gov/planetary/apod",
                    params={"api_key": api_key},
                    timeout=_FETCH_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.error(
                            "xOTD instance '%s': NASA APOD HTTP %s",
                            instance.instance_id, resp.status,
                        )
                        return
                    data = await resp.json()
                if data.get("media_type") != "image":
                    _LOGGER.info(
                        "xOTD instance '%s': today's APOD is not an image (media_type=%s), skipping",
                        instance.instance_id, data.get("media_type"),
                    )
                    return
                image_url = data.get("hdurl") or data.get("url")
                filename = f"apod_{data.get('date', today.strftime('%Y-%m-%d'))}.jpg"

            elif provider == "wikimedia_potd":
                url = f"https://en.wikipedia.org/api/rest_v1/feed/featured/{today.strftime('%Y/%m/%d')}"
                async with session.get(url, timeout=_FETCH_TIMEOUT) as resp:
                    if resp.status != 200:
                        _LOGGER.error(
                            "xOTD instance '%s': Wikimedia POTD HTTP %s",
                            instance.instance_id, resp.status,
                        )
                        return
                    data = await resp.json()
                image = (data.get("image") or {}).get("image") or {}
                image_url = image.get("source")
                if not image_url:
                    _LOGGER.error(
                        "xOTD instance '%s': Wikimedia POTD response missing an image",
                        instance.instance_id,
                    )
                    return
                basename = os.path.basename(urllib.parse.urlparse(image_url).path)
                filename = basename or f"wikimedia_potd_{today.strftime('%Y-%m-%d')}.jpg"

            elif provider == "bing_wallpaper":
                async with session.get(
                    "https://www.bing.com/HPImageArchive.aspx",
                    params={"format": "js", "idx": "0", "n": "1", "mkt": "en-US"},
                    timeout=_FETCH_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.error(
                            "xOTD instance '%s': Bing wallpaper HTTP %s",
                            instance.instance_id, resp.status,
                        )
                        return
                    data = await resp.json()
                images = data.get("images") or []
                if not images:
                    _LOGGER.error(
                        "xOTD instance '%s': Bing wallpaper response had no images",
                        instance.instance_id,
                    )
                    return
                image_url = f"https://www.bing.com{images[0]['url']}"
                filename = f"bing_wallpaper_{images[0].get('startdate', today.strftime('%Y%m%d'))}.jpg"

            else:
                _LOGGER.error(
                    "xOTD instance '%s': unknown feed_provider %r",
                    instance.instance_id, provider,
                )
                return

            async with session.get(image_url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.error(
                        "xOTD instance '%s': HTTP %s downloading image",
                        instance.instance_id, resp.status,
                    )
                    return
                image_bytes = await resp.read()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "xOTD instance '%s': failed to fetch %s feed: %s",
                instance.instance_id, provider, err,
            )
            return

        record = await self._library.async_upload(filename, image_bytes, albums=[_IMAGE_OTD_ALBUM])
        await self._async_send_image_to_frame(instance, record["image_id"])

    async def _async_run_image_album(self, instance: XotdInstance) -> None:
        album = instance.mode_config.get("album")
        images = await self._library.async_list_images()
        candidates = [img for img in images if album in (img.get("albums") or [])]
        if not candidates:
            _LOGGER.warning(
                "xOTD instance '%s': album '%s' has no images", instance.instance_id, album
            )
            return
        image_id = random.choice(candidates)["image_id"]
        await self._async_send_image_to_frame(instance, image_id)
