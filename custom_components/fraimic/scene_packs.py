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

_INDEX_CACHE_TTL = 3600  # seconds -- avoid re-fetching the catalog on every panel load
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
        self._index_cache: list[dict[str, Any]] | None = None
        self._index_cache_time: float = 0.0

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self._installed = dict((stored or {}).get("installed") or {})

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
                }
            )
        return result

    async def _async_get_pack(self, pack_id: str) -> dict[str, Any]:
        for pack in await self._async_fetch_index():
            if pack["id"] == pack_id:
                return pack
        raise ScenePackError(f"Scene pack '{pack_id}' not found")

    async def async_install_pack(self, pack_id: str) -> dict[str, Any]:
        if pack_id in self._installed:
            raise ScenePackError(
                f"Pack '{pack_id}' is already installed -- remove it first to reinstall"
            )

        pack = await self._async_get_pack(pack_id)
        album = pack["name"]
        session = async_get_clientsession(self.hass)

        from PIL import Image  # noqa: PLC0415

        def _dimensions(raw_bytes: bytes) -> tuple[int, int]:
            with Image.open(io.BytesIO(raw_bytes)) as img:
                return img.size

        # Each image is fetched/uploaded independently -- one broken URL or
        # decode failure shouldn't strand the rest of the pack, same
        # philosophy as the multi-file library upload endpoint.
        uploaded: list[tuple[str, bool]] = []  # (image_id, is_landscape)
        errors: list[dict[str, str]] = []

        for image_spec in pack.get("images", []):
            filename = image_spec.get("filename") or "image.jpg"
            path = image_spec.get("path")
            url = f"{SCENE_PACK_RAW_BASE}/{path}"
            try:
                async with session.get(url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                    if resp.status != 200:
                        raise ScenePackError(f"HTTP {resp.status} fetching {filename}")
                    raw_bytes = await resp.read()
                width, height = await self.hass.async_add_executor_job(
                    _dimensions, raw_bytes
                )
                record = await self._library.async_upload(filename, raw_bytes, [album])
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Scene pack '%s': failed to import '%s': %s", pack_id, filename, err
                )
                errors.append({"filename": filename, "message": str(err)})
                continue
            uploaded.append((record["image_id"], width > height))

        if not uploaded:
            raise ScenePackError(
                f"Couldn't import any images for pack '{pack['name']}': "
                + (errors[0]["message"] if errors else "unknown error")
            )

        frames: list[tuple[str, bool]] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get("kind") == KIND_SCENES_HUB:
                continue
            width = entry.data.get(CONF_WIDTH)
            height = entry.data.get(CONF_HEIGHT)
            if isinstance(width, int) and isinstance(height, int):
                frames.append((entry.entry_id, width > height))

        scene_id = None
        if frames:
            mappings = _assign_images_to_frames(frames, uploaded)
            if mappings:
                scene = await self._scenes.async_save_scene(
                    name=pack["name"], mappings=mappings, album=album
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

    async def async_uninstall_pack(self, pack_id: str) -> None:
        installed = self._installed.get(pack_id)
        if installed is None:
            raise ScenePackError(f"Pack '{pack_id}' is not installed")

        if installed.get("scene_id"):
            await self._scenes.async_delete_scene(installed["scene_id"])
        for image_id in installed.get("image_ids", []):
            try:
                await self._library.async_delete(image_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Scene pack '%s': failed to delete image '%s': %s",
                    pack_id,
                    image_id,
                    err,
                )

        del self._installed[pack_id]
        await self._async_persist()
