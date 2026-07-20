"""Scene packs: curated bundles of public-domain images plus an
auto-assembled scene.

Content (a manifest and its source images) lives in this same repo under
scene_packs/ and is fetched at install time from GitHub raw content -- see
SCENE_PACK_INDEX_URL in const.py. Installing a pack downloads its images
through the same LibraryManager.async_upload() pipeline a manual upload
uses, so images end up wherever the user's library is already configured to
live (Local/Dropbox/Google Drive) and get the normal per-resolution .bin
conversion -- packs never ship pre-baked .bin files, since those are keyed
to each user's specific frame resolutions and byte layout (see
image_converter.py) and would go stale the moment a new panel size ships.

Installing also auto-builds a ready-to-send Scene by assigning each
downloaded image to one of the user's configured frames, matching frame
orientation to image orientation where possible -- no manual mapping step
required.
"""

from __future__ import annotations

import io
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    ADDONS_DIRNAME,
    CONF_HEIGHT,
    CONF_WIDTH,
    DOMAIN,
    KIND_SCENES_HUB,
    SCENE_PACK_INDEX_URL,
    SCENE_PACK_RAW_BASE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .library import LibraryManager
    from .scenes import SceneManager

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}_scene_packs"
_STORAGE_VERSION = 1

_INDEX_CACHE_TTL = 60  # seconds -- avoid re-fetching the catalog on every panel load
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

class ScenePackError(Exception):
    """Raised for invalid scene pack operations (unknown pack, fetch
    failure, already installed, not installed)."""


def _assign_images_to_frames(
    frames: list[tuple[str, bool]], images: list[tuple[str, bool]]
) -> dict[str, str]:
    """Orientation-aware round robin: map each frame (entry_id,
    is_landscape) to one image_id, preferring images that share the frame's
    orientation.

    Portrait and landscape images are cycled from independent pools so
    frames of one orientation don't exhaust images meant for the other. A
    frame only draws from the opposite-orientation pool (still round robin,
    over every downloaded image) if its own orientation's pool is empty.
    """
    portrait = [image_id for image_id, is_landscape in images if not is_landscape]
    landscape = [image_id for image_id, is_landscape in images if is_landscape]
    everything = [image_id for image_id, _ in images]

    pools = {"portrait": portrait, "landscape": landscape, "all": everything}
    counters = {"portrait": 0, "landscape": 0, "all": 0}
    mappings: dict[str, str] = {}

    for entry_id, frame_is_landscape in frames:
        pool_name = "landscape" if frame_is_landscape else "portrait"
        if not pools[pool_name]:
            pool_name = "all"
        pool = pools[pool_name]
        if not pool:
            continue
        mappings[entry_id] = pool[counters[pool_name] % len(pool)]
        counters[pool_name] += 1

    return mappings


class ScenePackManager:
    """Owns the remote catalog cache and the set of installed packs."""

    def __init__(
        self,
        hass: "HomeAssistant",
        library: "LibraryManager",
        scenes: "SceneManager",
    ) -> None:
        self.hass = hass
        self._library = library
        self._scenes = scenes
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._installed: dict[str, dict[str, Any]] = {}
        self._installing: set[str] = set()
        self._index_cache: list[dict[str, Any]] | None = None
        self._index_cache_time: float = 0.0

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self._installed = dict((stored or {}).get("installed") or {})
        # Content Platform Phase 6: no widget schedulers to re-arm.

    def installed_scene_ids(self) -> set[str]:
        """Scene ids created by any currently-installed pack -- used to
        backfill Scene.source for scenes from packs installed before that
        field existed (see SceneManager.async_mark_scene_source)."""
        return {
            installed["scene_id"]
            for installed in self._installed.values()
            if installed.get("scene_id")
        }

    async def _async_persist(self) -> None:
        await self._store.async_save({"installed": self._installed})

    async def _async_fetch_index(self) -> list[dict[str, Any]]:
        now = time.time()
        if self._index_cache is not None and now - self._index_cache_time < _INDEX_CACHE_TTL:
            return self._index_cache

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(SCENE_PACK_INDEX_URL, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ScenePackError(
                        f"Scene pack catalog returned HTTP {resp.status}"
                    )
                # raw.githubusercontent.com serves this as text/plain, not
                # application/json -- content_type=None skips aiohttp's
                # strict content-type check on an otherwise-valid JSON body.
                data = await resp.json(content_type=None)
        except ScenePackError:
            raise
        except Exception as err:  # noqa: BLE001
            raise ScenePackError(
                f"Couldn't reach the scene pack catalog: {err}"
            ) from err

        packs = data.get("packs") if isinstance(data, dict) else None
        if not isinstance(packs, list):
            raise ScenePackError("Scene pack catalog is malformed")

        # Gallery is art-only — drop any legacy widget entries if a stale
        # index still lists them (Content Platform Phase 5/6).
        packs = [p for p in packs if isinstance(p, dict) and p.get("type") != "widget"]

        self._index_cache = packs
        self._index_cache_time = now
        return packs

    async def async_list_available(self) -> list[dict[str, Any]]:
        packs = await self._async_fetch_index()
        result = []
        for pack in packs:
            installed = self._installed.get(pack["id"])
            result.append(
                {
                    **pack,
                    "installed": installed is not None,
                    "scene_created": bool(installed and installed.get("scene_id")),
                    "config": installed.get("config") if installed else None,
                }
            )
        return result

    async def async_get_pack(self, pack_id: str) -> dict[str, Any]:
        """Look up one catalog entry by id -- public since SkillManager also
        needs the "xotd" pack's script_url/config_schema for its own
        per-render script execution (see skills.py)."""
        for pack in await self._async_fetch_index():
            if pack["id"] == pack_id:
                return pack
        raise ScenePackError(f"Scene pack '{pack_id}' not found")

    async def _async_import_image(
        self, session: aiohttp.ClientSession, pack_id: str, image_spec: dict[str, Any], album: str
    ) -> tuple[str, bool]:
        """Fetch one pack image from GitHub and upload it into the album.
        Returns (image_id, is_landscape). Raises on any failure -- callers
        catch per-image so one broken URL or decode failure doesn't strand
        the rest of the pack, same philosophy as the multi-file library
        upload endpoint."""
        from PIL import Image  # noqa: PLC0415

        def _dimensions(raw_bytes: bytes) -> tuple[int, int]:
            with Image.open(io.BytesIO(raw_bytes)) as img:
                return img.size

        filename = image_spec.get("filename") or "image.jpg"
        path = image_spec.get("path")
        url = f"{SCENE_PACK_RAW_BASE}/{path}"
        async with session.get(url, timeout=_DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                raise ScenePackError(f"HTTP {resp.status} fetching {filename}")
            raw_bytes = await resp.read()
        width, height = await self.hass.async_add_executor_job(_dimensions, raw_bytes)
        record = await self._library.async_upload(filename, raw_bytes, [album])
        title = image_spec.get("title")
        if title:
            await self._library.async_set_image_voice_name(record["image_id"], title)
        return record["image_id"], width > height

    async def async_install_pack(
        self,
        pack_id: str,
        config_data: dict[str, Any] = None,
        *,
        create_scene: bool = True,
    ) -> dict[str, Any]:
        """Install a Gallery art pack (or widget tool).

        *create_scene* (art packs only, default True): also auto-build a
        scene mapping images to configured frames. Set False for
        library-only installs (Content Platform Phase 2).
        """
        pack = await self.async_get_pack(pack_id)

        if pack.get("type") == "widget":
            # Content Platform Phase 5: widgets retired. Daily Agenda is a
            # Live skill (content_mode=agenda); do not re-introduce frame-IP
            # subprocess installs.
            raise ScenePackError(
                f"'{pack.get('name', pack_id)}' is no longer installed from "
                "Gallery. Open the Live tab and use Daily Agenda (or create "
                "an agenda preset), then schedule it like other live content."
            )

        if pack_id in self._installed:
            raise ScenePackError(
                f"Pack '{pack_id}' is already installed -- remove it first to reinstall"
            )
        if pack_id in self._installing:
            raise ScenePackError(f"Pack '{pack_id}' is already being installed")

        album = pack["name"]
        session = async_get_clientsession(self.hass)

        # Each image is fetched/uploaded independently -- one broken URL or
        # decode failure shouldn't strand the rest of the pack, same
        # philosophy as the multi-file library upload endpoint.
        uploaded: list[tuple[str, bool]] = []  # (image_id, is_landscape)
        errors: list[dict[str, str]] = []

        self._installing.add(pack_id)
        try:
            for image_spec in pack.get("images", []):
                filename = image_spec.get("filename") or "image.jpg"
                try:
                    uploaded.append(
                        await self._async_import_image(session, pack_id, image_spec, album)
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "Scene pack '%s': failed to import '%s': %s", pack_id, filename, err
                    )
                    errors.append({"filename": filename, "message": str(err)})
        finally:
            self._installing.discard(pack_id)
            # However this exits -- including cancellation from a client
            # timeout or disconnect partway through, which the loop's
            # `except Exception` above can't catch -- remember whatever
            # actually made it into the library. Otherwise the "already
            # installed" guard above never trips, and a retry blindly
            # re-uploads duplicates of the images that already succeeded
            # while the rest of the pack silently never lands.
            if uploaded and pack_id not in self._installed:
                self._installed[pack_id] = {
                    "album": album,
                    "scene_id": None,
                    "image_ids": [image_id for image_id, _ in uploaded],
                    "installed_at": time.time(),
                }
                await self._async_persist()

        if not uploaded:
            raise ScenePackError(
                f"Couldn't import any images for pack '{pack['name']}': "
                + (errors[0]["message"] if errors else "unknown error")
            )

        scene_id = None
        if create_scene:
            frames: list[tuple[str, bool]] = []
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get("kind") == KIND_SCENES_HUB:
                    continue
                width = entry.data.get(CONF_WIDTH)
                height = entry.data.get(CONF_HEIGHT)
                if isinstance(width, int) and isinstance(height, int):
                    # Match pack images against the frame's *effective*
                    # orientation (honours the orientation lock), not the
                    # panel's native buffer orientation.
                    from .helpers import render_spec_for_entry  # noqa: PLC0415

                    spec = render_spec_for_entry(entry)
                    frames.append((entry.entry_id, spec.width > spec.height))

            if frames:
                mappings = _assign_images_to_frames(frames, uploaded)
                if mappings:
                    scene = await self._scenes.async_save_scene(
                        name=pack["name"],
                        mappings=mappings,
                        album=album,
                        source="addon",
                    )
                    scene_id = scene["scene_id"]

        self._installed[pack_id] = {
            "album": album,
            "scene_id": scene_id,
            "image_ids": [image_id for image_id, _ in uploaded],
            "installed_at": time.time(),
        }
        await self._async_persist()

        return {
            "success": True,
            "pack_id": pack_id,
            "images_added": len(uploaded),
            "scene_created": scene_id is not None,
            "errors": errors,
        }

    async def async_sync_pack(self, pack_id: str) -> dict[str, Any]:
        """Re-fetch whatever a pack's catalog entry has that this install
        is missing -- covers both a broken install (an image that failed
        to land, or was later lost to something like the manifest race
        _async_install_pack's `uploaded` list guards against) and a pack
        that's grown new images since it was installed. Matches by
        filename against the pack's current image list rather than trusting
        the stored image_ids alone, since those can point at images that
        no longer exist. Never touches the scene mapping -- a user may have
        hand-edited it, so newly recovered images just land in the album."""
        installed = self._installed.get(pack_id)
        if installed is None:
            raise ScenePackError(f"Pack '{pack_id}' is not installed")
        if installed.get("type") == "widget":
            raise ScenePackError(
                f"Pack '{pack_id}' is a legacy widget — remove it and use "
                "Live → Daily Agenda instead"
            )
        if pack_id in self._installing:
            raise ScenePackError(f"Pack '{pack_id}' is already being installed")

        pack = await self.async_get_pack(pack_id)
        album = installed.get("album", pack["name"])
        session = async_get_clientsession(self.hass)

        library_images = await self._library.async_list_images()
        existing_ids = {img["image_id"] for img in library_images}
        tracked_ids = set(installed.get("image_ids", []))
        present_filenames = {
            img["filename"] for img in library_images if img["image_id"] in tracked_ids
        }

        missing_specs = [
            spec for spec in pack.get("images", [])
            if (spec.get("filename") or "image.jpg") not in present_filenames
        ]

        added: list[tuple[str, bool]] = []
        errors: list[dict[str, str]] = []

        self._installing.add(pack_id)
        try:
            for image_spec in missing_specs:
                filename = image_spec.get("filename") or "image.jpg"
                try:
                    added.append(
                        await self._async_import_image(session, pack_id, image_spec, album)
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "Scene pack '%s': sync failed to import '%s': %s", pack_id, filename, err
                    )
                    errors.append({"filename": filename, "message": str(err)})
        finally:
            self._installing.discard(pack_id)
            # Drop any tracked id that no longer resolves to a real image
            # (that's exactly what made it "missing" above) and add
            # whatever was freshly recovered -- even on a mid-sync
            # disconnect, so a cancelled sync doesn't lose already-added
            # images the same way an uninterrupted one wouldn't.
            surviving_ids = [iid for iid in installed.get("image_ids", []) if iid in existing_ids]
            installed["image_ids"] = surviving_ids + [image_id for image_id, _ in added]
            await self._async_persist()

        return {
            "success": True,
            "pack_id": pack_id,
            "images_added": len(added),
            "already_ok": len(pack.get("images", [])) - len(missing_specs),
            "errors": errors,
        }

    async def async_uninstall_pack(self, pack_id: str) -> None:
        installed = self._installed.get(pack_id)
        if installed is None:
            raise ScenePackError(f"Pack '{pack_id}' is not installed")

        if installed.get("type") == "widget":
            # Leftover Phase-4-era widget install: delete on-disk files only.
            import os
            import shutil

            addon_dir = self.hass.config.path(ADDONS_DIRNAME, pack_id)
            if os.path.exists(addon_dir):
                await self.hass.async_add_executor_job(shutil.rmtree, addon_dir)
            del self._installed[pack_id]
            await self._async_persist()
            return

        if installed.get("scene_id"):
            await self._scenes.async_delete_scene(installed["scene_id"])

        # Get all library images to check their album tags
        library_images = await self._library.async_list_images()
        images_by_id = {img["image_id"]: img for img in library_images}
        pack = await self.async_get_pack(pack_id)
        album_to_remove = installed.get("album", pack["name"])

        remaining: list[str] = []
        for image_id in installed.get("image_ids", []):
            try:
                img = images_by_id.get(image_id)
                if img:
                    other_albums = [a for a in img.get("albums", []) if a != album_to_remove]
                    if other_albums:
                        # Image is tagged with other albums; remove only the pack's album tag and retain the image.
                        await self._library.async_set_image_albums(image_id, other_albums)
                        continue
                await self._library.async_delete(image_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Scene pack '%s': failed to delete or untag image '%s': %s",
                    pack_id,
                    image_id,
                    err,
                )
                remaining.append(image_id)

        if remaining:
            # Don't forget these -- if we cleared tracking here, they'd
            # become permanently orphaned (nothing else in this codebase
            # ever looks for images outside a tracked pack's list), and a
            # reinstall would still be blocked to boot since the caller
            # sees this as failed, not "already installed".
            installed["scene_id"] = None
            installed["image_ids"] = remaining
            await self._async_persist()
            raise ScenePackError(
                f"Removed the scene, but {len(remaining)} image(s) couldn't be "
                f"deleted -- try removing '{pack_id}' again."
            )

        del self._installed[pack_id]
        await self._async_persist()

    def unload(self) -> None:
        """No-op: widget timers retired (Content Platform Phase 6)."""


