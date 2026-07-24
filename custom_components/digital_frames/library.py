"""Pluggable storage backends for the Fraimic shared image library.

The library holds a single shared pool of source images. Each image gets a
pre-converted .bin generated once per distinct (width, height) resolution in
use across the user's configured frames -- NOT one per individual frame --
so any frame sharing that resolution sends the cached bytes with zero extra
conversion work. A resolution that shows up later (e.g. a newly added frame
with a different panel size) is generated lazily on first send to a frame of
that size, then cached from then on.

Storage backend is pluggable. LocalLibraryBackend (this HA install's own
storage), DropboxLibraryBackend (a long-lived access token), and
GoogleDriveLibraryBackend (OAuth2 with a refresh token, connected through the
panel's "Connect Google Drive" flow) are all fully implemented.
"""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    CACHE_DIRNAME,
    CONF_HEIGHT,
    CONF_WIDTH,
    DOMAIN,
    LEGACY_CACHE_DIRNAME,
    LEGACY_DOMAIN,
    LEGACY_LIBRARY_DIRNAME,
    LIBRARY_DIRNAME,
)
from .helpers import RenderSpec, render_spec_for_entry, render_spec_for_hass_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SETTINGS_STORAGE_KEY = f"{DOMAIN}_library_settings"
_LEGACY_SETTINGS_STORAGE_KEY = f"{LEGACY_DOMAIN}_library_settings"
_SETTINGS_STORAGE_VERSION = 1

BACKEND_LOCAL = "local"
BACKEND_GOOGLE_DRIVE = "google_drive"
BACKEND_DROPBOX = "dropbox"


def _migrate_local_dirname(hass: "HomeAssistant", *, new: str, legacy: str) -> str:
    """Return *new* config path, renaming *legacy* → *new* once if needed.

    Used for the photo library (albums live in the manifest under this root)
    and related cache dirs. Safe if only one of the paths exists.
    """
    import shutil

    new_path = hass.config.path(new)
    legacy_path = hass.config.path(legacy)
    if os.path.isdir(new_path):
        return new_path
    if os.path.isdir(legacy_path):
        try:
            shutil.move(legacy_path, new_path)
            _LOGGER.info("Migrated %s → %s", legacy_path, new_path)
        except OSError as err:
            _LOGGER.warning(
                "Could not rename %s to %s (%s); using legacy path",
                legacy_path,
                new_path,
                err,
            )
            return legacy_path
    return new_path

# Sentinel queued onto LibraryManager._backfill_pending to mean "check every
# image for missing .bin resolutions", as opposed to one specific image_id.
_BACKFILL_SWEEP_ALL = "*"

# Every image belongs to at least this album. It's a normal tag like any
# other -- not a computed "all photos" view -- except it can't be renamed or
# deleted, so there's always at least one folder every photo is reachable
# from even after being fully reorganized into other albums.
DEFAULT_ALBUM = "Images"


def _normalize_albums(albums: list[str] | None) -> list[str]:
    """Strip/dedupe (order-preserving) album names, falling back to the
    default album if the result would otherwise be empty."""
    seen: list[str] = []
    for name in albums if isinstance(albums, list) else []:
        name = (name or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen or [DEFAULT_ALBUM]


def _normalize_tags(tags: list[str] | None) -> list[str]:
    """Strip/dedupe (order-preserving) tag names, converting to lowercase for de-duplication
    but preserving original casing."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags if isinstance(tags, list) else []:
        tag = (tag or "").strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            cleaned.append(tag)
    return cleaned

_CONTENT_TYPE_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "HEIC": "image/heic",
}


def _detect_content_type(raw_bytes: bytes) -> str:
    """Best-effort sniff of an uploaded image's MIME type."""
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(raw_bytes)) as img:
            fmt = (img.format or "").upper()
    except Exception:  # noqa: BLE001
        fmt = ""
    return _CONTENT_TYPE_BY_FORMAT.get(fmt, "application/octet-stream")


def _all_render_specs(hass: "HomeAssistant") -> set[RenderSpec]:
    """Distinct render specs (effective resolution + rotation + lock) across
    every configured frame. Two frames with identical settings collapse to
    one spec (they share cached payload files *when codec also matches*)."""
    specs: set[RenderSpec] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("kind") == "scenes_hub":
            continue
        width = entry.data.get(CONF_WIDTH)
        height = entry.data.get(CONF_HEIGHT)
        if isinstance(width, int) and isinstance(height, int):
            specs.add(render_spec_for_hass_entry(hass, entry))
    return specs


def _all_render_targets(hass: "HomeAssistant") -> list[tuple[RenderSpec, str]]:
    """(RenderSpec, codec_id) pairs for every configured frame.

    Distinct by (spec, codec_id) so Meural JPEG and Spectra at the same
    geometry never share a cache slot incorrectly.
    """
    from .panel_codec import panel_codec_for_entry  # noqa: PLC0415

    seen: set[tuple[RenderSpec, str]] = set()
    out: list[tuple[RenderSpec, str]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("kind") == "scenes_hub":
            continue
        width = entry.data.get(CONF_WIDTH)
        height = entry.data.get(CONF_HEIGHT)
        if not (isinstance(width, int) and isinstance(height, int)):
            continue
        try:
            codec_id = panel_codec_for_entry(entry).id
        except ValueError:
            continue
        spec = render_spec_for_hass_entry(hass, entry)
        key = (spec, codec_id)
        if key in seen:
            continue
        seen.add(key)
        out.append((spec, codec_id))
    return out


# Every cache-key suffix a .bin file can be stored under (see
# RenderSpec.variant): 4 rotations x locked/unlocked. Used to invalidate
# *all* renders of one image+resolution when its crop changes -- deleting
# only the base variant would leave rotated/locked renders stale.
_ALL_BIN_VARIANTS: tuple[str, ...] = tuple(
    (f"_r{rot}" if rot else "") + ("_c" if locked else "")
    for locked in (False, True)
    for rot in (0, 90, 180, 270)
)


def _known_codec_ids() -> tuple[str, ...]:
    """All PanelCodec ids that may appear under bin/ (FramePort Phase 2)."""
    from .panel_codec import CODECS  # noqa: PLC0415

    return tuple(CODECS.keys())


def _bin_res_key(width: int, height: int, variant: str = "") -> str:
    """Resolution + render-variant segment of the .bin cache path/key."""
    return f"{width}x{height}{variant}"


def _bin_manifest_key(
    width: int, height: int, variant: str = "", codec_id: str = ""
) -> str:
    """Drive-style bin_file_ids key: res[+variant][/codec_id].

    Empty *codec_id* is the pre-Phase-2 legacy key (resolution only).
    """
    base = _bin_res_key(width, height, variant)
    return f"{base}/{codec_id}" if codec_id else base


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:128] or "image"


# image_id is always generated as uuid.uuid4().hex[:12] (see
# async_upload_original on every backend). Every call site that
# interpolates a caller-supplied image_id directly into a filesystem path
# or cloud API path (rather than looking it up against the manifest first)
# must validate it against this shape -- otherwise a crafted
# "../../etc/passwd"-style image_id reaches _bin_path/_thumb_path
# unsanitized (unlike filenames, which always go through _safe_filename).
_IMAGE_ID_RE = re.compile(r"^[0-9a-f]{6,40}$")


def _safe_image_id(image_id: str) -> str:
    if not isinstance(image_id, str) or not _IMAGE_ID_RE.match(image_id):
        raise ValueError(f"Invalid image_id: {image_id!r}")
    return image_id


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LibraryImage:
    """One image in the shared library."""

    image_id: str
    filename: str
    uploaded_at: float
    content_type: str = "application/octet-stream"
    resolutions: list[list[int]] = field(default_factory=list)  # [[w, h], ...]
    # Per-resolution manual crop rectangles, keyed by "WIDTHxHEIGHT".
    # Each value is [x0, y0, x1, y1], normalized 0.0-1.0 against the
    # original image. Absent key == no manual crop saved for that
    # resolution yet (falls back to the automatic centered cover-crop).
    crops: dict[str, list[float]] = field(default_factory=dict)
    # Album tags this image belongs to. Not folders -- an image can carry
    # any number of these with no duplication of the underlying file.
    albums: list[str] = field(default_factory=lambda: [DEFAULT_ALBUM])
    # User-defined voice name for voice control matching.
    voice_name: str | None = None
    # User-defined tags for categorizing/matching.
    tags: list[str] = field(default_factory=list)

    def has_resolution(self, width: int, height: int) -> bool:
        return [width, height] in self.resolutions

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "filename": self.filename,
            "uploaded_at": self.uploaded_at,
            "content_type": self.content_type,
            "resolutions": self.resolutions,
            "crops": self.crops,
            "albums": self.albums,
            "voice_name": self.voice_name,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LibraryImage":
        return cls(
            image_id=data["image_id"],
            filename=data["filename"],
            uploaded_at=data["uploaded_at"],
            content_type=data.get("content_type", "application/octet-stream"),
            resolutions=data.get("resolutions", []),
            crops=data.get("crops", {}),
            albums=_normalize_albums(data.get("albums")),
            voice_name=data.get("voice_name"),
            tags=data.get("tags", []),
        )


class LibraryBackendError(Exception):
    """Raised when a backend can't be used (bad/missing credentials, not yet
    implemented, network failure, etc.)."""


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class LibraryBackend:
    """Abstract interface every storage backend implements."""

    name = "abstract"

    # Whether this backend can find files added outside the app (e.g. a
    # photo dropped straight into cloud storage) and adopt them into the
    # manifest. False by default -- only backends that override
    # async_discover_new_files() and flip this on actually support it.
    supports_discovery = False

    async def async_setup(self) -> None:
        """Validate connectivity/credentials. Raise LibraryBackendError on failure."""

    async def async_list_images(self) -> list[LibraryImage]:
        raise NotImplementedError

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        """Return (raw_bytes, content_type) for the stored original."""
        raise NotImplementedError

    async def async_get_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> bytes | None:
        """*variant* is the cache-key suffix from RenderSpec.variant ("" for
        the default render, e.g. "_r180" / "_r90_c" otherwise).

        *codec_id* is the PanelCodec id (e.g. spectra6_sequential). When set,
        backends look under the codec-keyed path first, then fall back to the
        pre-Phase-2 resolution-only path so existing caches keep working.
        """
        raise NotImplementedError

    async def async_save_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        data: bytes,
        variant: str = "",
        codec_id: str = "",
    ) -> None:
        """Persist a wire payload. Prefer a non-empty *codec_id* (Phase 2)."""
        raise NotImplementedError

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        """Patch arbitrary manifest fields (e.g. crops) for one image."""
        raise NotImplementedError

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        """Patch arbitrary manifest fields for many images (keyed by
        image_id) in a single manifest read + write, instead of one
        round-trip per image -- used for album rename/delete, which can
        touch every image in the library at once."""
        raise NotImplementedError

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        """Remove every cached .bin variant for one resolution so they all
        regenerate on next send (crops apply to all rotations/locks alike)."""
        raise NotImplementedError

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        raise NotImplementedError

    async def async_delete_image(self, image_id: str) -> None:
        raise NotImplementedError

    async def async_discover_new_files(self) -> list[LibraryImage]:
        """Find files added outside the app and adopt them into the
        manifest, returning the newly-adopted records. Only meaningful when
        supports_discovery is True."""
        raise NotImplementedError

    async def async_get_local_path(self, image_id: str) -> str:
        """Return the absolute path to a local copy of the original image."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Local (HA-server) backend -- fully implemented
# ---------------------------------------------------------------------------


class LocalLibraryBackend(LibraryBackend):
    """Stores the library under ``<config>/digital_frames_library/``.

    On first setup after the product rename, renames a leftover
    ``fraimic_library/`` directory into place so albums and originals move
    with the brand.
    """

    name = BACKEND_LOCAL

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self.settings: dict[str, Any] = {"backend": BACKEND_LOCAL}
        # Path finalized in async_setup after one-shot rename.
        self._root = hass.config.path(LIBRARY_DIRNAME)
        self._manifest_path = os.path.join(self._root, "manifest.json")
        # Guards every manifest read-modify-write below: each one runs as
        # its own executor job, and the background backfill worker can have
        # one in flight at the same time as a fresh upload's -- without
        # this, whichever finishes last wins and silently clobbers the
        # other's change (e.g. a scene pack install racing its own
        # backfill and losing images it just added).
        self._manifest_lock = asyncio.Lock()

    async def async_setup(self) -> None:
        def _prepare() -> None:
            self._root = _migrate_local_dirname(
                self.hass, new=LIBRARY_DIRNAME, legacy=LEGACY_LIBRARY_DIRNAME
            )
            self._manifest_path = os.path.join(self._root, "manifest.json")
            self._ensure_dirs()
            self._migrate_stale_cache()

        await self.hass.async_add_executor_job(_prepare)

    # -- sync helpers (always run via executor) --

    def _migrate_stale_cache(self) -> None:
        marker_path = os.path.join(self._root, "bin", ".migrated_v0.9.1")
        if not os.path.exists(marker_path):
            _LOGGER.info("Clearing stale image bin cache for layout updates")
            bin_dir = os.path.join(self._root, "bin")
            if os.path.exists(bin_dir):
                import shutil
                try:
                    shutil.rmtree(bin_dir)
                except Exception as err:
                    _LOGGER.warning("Failed to clear stale bin cache directory: %s", err)
            os.makedirs(bin_dir, exist_ok=True)
            with open(marker_path, "w") as f:
                f.write("migrated")

    def _ensure_dirs(self) -> None:
        os.makedirs(self._root, exist_ok=True)
        os.makedirs(os.path.join(self._root, "originals"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "bin"), exist_ok=True)
        if not os.path.isfile(self._manifest_path):
            with open(self._manifest_path, "w", encoding="utf-8") as f:
                json.dump({"images": []}, f)

    def _read_manifest(self) -> dict[str, Any]:
        if not os.path.isfile(self._manifest_path):
            return {"images": []}
        with open(self._manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        tmp = self._manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, self._manifest_path)

    def _bin_path(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> str:
        # Phase 2: bin/<WxH[variant]>/<codec_id>/<image_id>.bin
        # Legacy (no codec_id): bin/<WxH[variant]>/<image_id>.bin
        image_id = _safe_image_id(image_id)
        res = _bin_res_key(width, height, variant)
        if codec_id:
            return os.path.join(
                self._root, "bin", res, codec_id, f"{image_id}.bin"
            )
        return os.path.join(self._root, "bin", res, f"{image_id}.bin")

    def _original_path_for(self, image_id: str, filename: str) -> str:
        return os.path.join(
            self._root, "originals", f"{image_id}_{_safe_filename(filename)}"
        )

    def _find_original_path(self, image_id: str) -> str | None:
        originals_dir = os.path.join(self._root, "originals")
        if not os.path.isdir(originals_dir):
            return None
        prefix = f"{image_id}_"
        for fn in os.listdir(originals_dir):
            if fn.startswith(prefix):
                return os.path.join(originals_dir, fn)
        return None

    def _list_images_sync(self) -> list[LibraryImage]:
        manifest = self._read_manifest()
        return [LibraryImage.from_dict(d) for d in manifest.get("images", [])]

    def _upload_original_sync(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        self._ensure_dirs()
        image_id = uuid.uuid4().hex[:12]
        path = self._original_path_for(image_id, filename)
        with open(path, "wb") as f:
            f.write(raw_bytes)
        record = LibraryImage(
            image_id=image_id,
            filename=filename,
            uploaded_at=time.time(),
            content_type=content_type,
            resolutions=[],
            albums=_normalize_albums(albums),
        )
        manifest = self._read_manifest()
        manifest.setdefault("images", []).append(record.to_dict())
        self._write_manifest(manifest)
        return record

    def _get_original_sync(self, image_id: str) -> tuple[bytes, str]:
        manifest = self._read_manifest()
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        content_type = entry.get("content_type", "application/octet-stream") if entry else "application/octet-stream"
        # The path is derivable from the manifest record (uploads write it
        # exactly this way) -- the originals/ directory scan is only a
        # fallback for files whose manifest filename doesn't match on disk.
        path = None
        if entry and entry.get("filename"):
            candidate = self._original_path_for(image_id, entry["filename"])
            if os.path.isfile(candidate):
                path = candidate
        if path is None:
            path = self._find_original_path(image_id)
        if path is None:
            raise LibraryBackendError(f"Original for image '{image_id}' not found")
        with open(path, "rb") as f:
            return f.read(), content_type

    def _get_bin_sync(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> bytes | None:
        if codec_id:
            path = self._bin_path(image_id, width, height, variant, codec_id)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return f.read()
            # Fall back to pre-Phase-2 layout for the same geometry.
            legacy = self._bin_path(image_id, width, height, variant, "")
            if os.path.isfile(legacy):
                with open(legacy, "rb") as f:
                    return f.read()
            return None
        path = self._bin_path(image_id, width, height, variant, "")
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _save_bin_sync(
        self,
        image_id: str,
        width: int,
        height: int,
        data: bytes,
        variant: str = "",
        codec_id: str = "",
    ) -> None:
        path = self._bin_path(image_id, width, height, variant, codec_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        manifest = self._read_manifest()
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                resolutions = d.setdefault("resolutions", [])
                if [width, height] not in resolutions:
                    resolutions.append([width, height])
                    # Only rewrite when something changed -- regenerations
                    # (rotation/lock variants, crop updates) hit this for
                    # already-recorded resolutions on every save.
                    self._write_manifest(manifest)
                break

    def _delete_image_sync(self, image_id: str) -> None:
        path = self._find_original_path(image_id)
        if path and os.path.isfile(path):
            os.remove(path)
        # Malformed ids (e.g. a double-click delete replaying an
        # already-removed id) no-op on the bin cache below rather than
        # raising -- but never let an unsanitized id reach _bin_path's
        # direct path interpolation (see _safe_image_id's docstring).
        safe_image_id = None
        try:
            safe_image_id = _safe_image_id(image_id)
        except ValueError:
            pass
        bin_root = os.path.join(self._root, "bin")
        if safe_image_id and os.path.isdir(bin_root):
            for res_dir in os.listdir(bin_root):
                res_path = os.path.join(bin_root, res_dir)
                # Legacy: bin/<res>/<id>.bin
                candidate = os.path.join(res_path, f"{safe_image_id}.bin")
                if os.path.isfile(candidate):
                    os.remove(candidate)
                # Phase 2: bin/<res>/<codec_id>/<id>.bin
                if os.path.isdir(res_path):
                    for sub in os.listdir(res_path):
                        codec_candidate = os.path.join(
                            res_path, sub, f"{safe_image_id}.bin"
                        )
                        if os.path.isfile(codec_candidate):
                            os.remove(codec_candidate)
        manifest = self._read_manifest()
        manifest["images"] = [
            d for d in manifest.get("images", []) if d["image_id"] != image_id
        ]
        self._write_manifest(manifest)

    def _update_image_fields_sync(self, image_id: str, fields: dict[str, Any]) -> None:
        manifest = self._read_manifest()
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                d.update(fields)
                break
        self._write_manifest(manifest)

    def _bulk_update_image_fields_sync(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        manifest = self._read_manifest()
        for d in manifest.get("images", []):
            fields = updates.get(d["image_id"])
            if fields:
                d.update(fields)
        self._write_manifest(manifest)

    def _delete_bin_sync(self, image_id: str, width: int, height: int) -> None:
        # Drop every render variant under every known codec + the legacy
        # resolution-only path so crop changes never leave a stale codec.
        for variant in _ALL_BIN_VARIANTS:
            for codec_id in (*_known_codec_ids(), ""):
                path = self._bin_path(image_id, width, height, variant, codec_id)
                if os.path.isfile(path):
                    os.remove(path)

    # -- async public API --

    async def async_list_images(self) -> list[LibraryImage]:
        return await self.hass.async_add_executor_job(self._list_images_sync)

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        return await self.hass.async_add_executor_job(self._get_original_sync, image_id)

    async def async_get_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(
            self._get_bin_sync, image_id, width, height, variant, codec_id
        )

    async def async_save_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        data: bytes,
        variant: str = "",
        codec_id: str = "",
    ) -> None:
        async with self._manifest_lock:
            await self.hass.async_add_executor_job(
                self._save_bin_sync, image_id, width, height, data, variant, codec_id
            )

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        async with self._manifest_lock:
            await self.hass.async_add_executor_job(
                self._update_image_fields_sync, image_id, fields
            )

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        async with self._manifest_lock:
            await self.hass.async_add_executor_job(
                self._bulk_update_image_fields_sync, updates
            )

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        await self.hass.async_add_executor_job(
            self._delete_bin_sync, image_id, width, height
        )

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        async with self._manifest_lock:
            return await self.hass.async_add_executor_job(
                self._upload_original_sync, filename, raw_bytes, content_type, albums
            )

    async def async_delete_image(self, image_id: str) -> None:
        async with self._manifest_lock:
            await self.hass.async_add_executor_job(self._delete_image_sync, image_id)

    async def async_get_local_path(self, image_id: str) -> str:
        return await self.hass.async_add_executor_job(self._get_local_path_sync, image_id)

    def _get_local_path_sync(self, image_id: str) -> str:
        manifest = self._read_manifest()
        entry = next((d for d in manifest.get("images", []) if d["image_id"] == image_id), None)
        path = None
        if entry and entry.get("filename"):
            candidate = self._original_path_for(image_id, entry["filename"])
            if os.path.isfile(candidate):
                path = candidate
        if path is None:
            path = self._find_original_path(image_id)
        if path is None:
            raise LibraryBackendError(f"Original for image '{image_id}' not found")
        return path


# ---------------------------------------------------------------------------
# Manifest cache for the cloud backends
# ---------------------------------------------------------------------------


class _ManifestCache:
    """Bounded-staleness in-memory copy of a cloud backend's manifest.

    Without this, every image fetch / list / album op re-downloads the entire
    manifest from Dropbox or Drive just to resolve one entry -- painting a
    grid of N images costs ~2N cloud round trips. All manifest writes in both
    cloud backends go through _write_manifest, which refreshes this cache, so
    within one HA instance it can never go stale. The TTL only bounds
    staleness against *out-of-band* writers (a second HA instance pointed at
    the same account -- already unsupported, since two instances' unlocked
    read-modify-writes clobber each other regardless of caching).

    get()/store() deep-copy in both directions: callers mutate the manifest
    they read before writing it back, and a failed write must leave the
    cached copy exactly as the remote still is.
    """

    def __init__(self, ttl: float = 300.0) -> None:
        self._value: dict[str, Any] | None = None
        self._fetched_at: float = 0.0
        self._ttl = ttl

    def get(self) -> dict[str, Any] | None:
        if self._value is None or (time.time() - self._fetched_at) >= self._ttl:
            return None
        return copy.deepcopy(self._value)

    def store(self, manifest: dict[str, Any]) -> None:
        self._value = copy.deepcopy(manifest)
        self._fetched_at = time.time()


# ---------------------------------------------------------------------------
# Dropbox backend -- a single long-lived access token, pasted in by the user
# ---------------------------------------------------------------------------

_DROPBOX_API = "https://api.dropboxapi.com/2"
_DROPBOX_CONTENT_API = "https://content.dropboxapi.com/2"
_DROPBOX_ROOT_NEW = f"/{LIBRARY_DIRNAME}"
_DROPBOX_ROOT_LEGACY = f"/{LEGACY_LIBRARY_DIRNAME}"


class DropboxLibraryBackend(LibraryBackend):
    """Stores the library in Dropbox under ``/digital_frames_library``.

    If a legacy ``/fraimic_library`` folder already has data, it is moved
    once to the new path (or used in place if the move fails).

    Auth is a single long-lived access token generated by the user in the
    Dropbox App Console -- no OAuth redirect dance needed.
    """

    name = BACKEND_DROPBOX
    supports_discovery = True

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = dict(settings)
        self._access_token = (self.settings.get("access_token") or "").strip()
        # Resolved in async_setup (may stay on legacy path if move fails).
        self._root = _DROPBOX_ROOT_NEW
        # See LocalLibraryBackend._manifest_lock -- same read-modify-write
        # race, just over the Dropbox API instead of a local file.
        self._manifest_lock = asyncio.Lock()
        self._manifest_cache = _ManifestCache()

    @property
    def _manifest_path(self) -> str:
        return f"{self._root}/manifest.json"

    @property
    def _inbox(self) -> str:
        return f"{self._root}/inbox"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if extra:
            headers.update(extra)
        return headers

    async def async_setup(self) -> None:
        if not self._access_token:
            raise LibraryBackendError(
                "Dropbox needs an access token -- generate one in the "
                "Dropbox App Console (App > Permissions > Generated access "
                "token) and paste it in."
            )
        session = async_get_clientsession(self.hass)
        try:
            resp = await session.post(
                f"{_DROPBOX_API}/users/get_current_account",
                headers=self._headers({"Content-Type": "application/json"}),
                data=b"null",
            )
        except Exception as err:  # noqa: BLE001
            raise LibraryBackendError(f"Couldn't reach Dropbox: {err}") from err
        if resp.status == 401:
            raise LibraryBackendError(
                "Dropbox rejected this access token (expired or invalid). "
                "Generate a new one in the Dropbox App Console."
            )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox connection check failed ({resp.status}): {text[:200]}"
            )
        self._root = await self._resolve_root()
        await self._ensure_manifest()

    async def _folder_exists(self, path: str) -> bool:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_API}/files/get_metadata",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": path},
        )
        if resp.status == 200:
            data = await resp.json()
            return data.get(".tag") == "folder" or data.get("tag") == "folder" or True
        return False

    async def _resolve_root(self) -> str:
        """Prefer /digital_frames_library; migrate /fraimic_library once."""
        new_exists = await self._folder_exists(_DROPBOX_ROOT_NEW)
        legacy_exists = await self._folder_exists(_DROPBOX_ROOT_LEGACY)
        if new_exists:
            return _DROPBOX_ROOT_NEW
        if not legacy_exists:
            return _DROPBOX_ROOT_NEW
        # Move legacy → new so albums land under the product name.
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_API}/files/move_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={
                "from_path": _DROPBOX_ROOT_LEGACY,
                "to_path": _DROPBOX_ROOT_NEW,
                "autorename": False,
            },
        )
        if resp.status < 400:
            _LOGGER.info(
                "Migrated Dropbox library %s → %s",
                _DROPBOX_ROOT_LEGACY,
                _DROPBOX_ROOT_NEW,
            )
            return _DROPBOX_ROOT_NEW
        text = await resp.text()
        _LOGGER.warning(
            "Could not rename Dropbox %s → %s (%s); using legacy path",
            _DROPBOX_ROOT_LEGACY,
            _DROPBOX_ROOT_NEW,
            text[:200],
        )
        return _DROPBOX_ROOT_LEGACY

    async def _ensure_manifest(self) -> None:
        manifest = await self._read_manifest()
        if manifest is None:
            await self._write_manifest({"images": []})

    async def _read_manifest(self) -> dict[str, Any] | None:
        cached = self._manifest_cache.get()
        if cached is not None:
            return cached
        manifest = await self._read_manifest_remote()
        if manifest is not None:
            self._manifest_cache.store(manifest)
        return manifest

    async def _read_manifest_remote(self) -> dict[str, Any] | None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/download",
            headers=self._headers(
                {"Dropbox-API-Arg": json.dumps({"path": self._manifest_path})}
            ),
        )
        if resp.status in (404, 409):
            return None
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox manifest read failed ({resp.status}): {text[:200]}"
            )
        data = await resp.read()
        return json.loads(data.decode("utf-8"))

    async def _write_manifest(self, manifest: dict[str, Any]) -> None:
        session = async_get_clientsession(self.hass)
        body = json.dumps(manifest).encode("utf-8")
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/upload",
            headers=self._headers(
                {
                    "Dropbox-API-Arg": json.dumps(
                        {"path": self._manifest_path, "mode": "overwrite"}
                    ),
                    "Content-Type": "application/octet-stream",
                }
            ),
            data=body,
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox manifest write failed ({resp.status}): {text[:200]}"
            )
        self._manifest_cache.store(manifest)

    def _bin_path(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> str:
        image_id = _safe_image_id(image_id)
        res = _bin_res_key(width, height, variant)
        if codec_id:
            return f"{self._root}/bin/{res}/{codec_id}/{image_id}.bin"
        return f"{self._root}/bin/{res}/{image_id}.bin"

    async def _original_dropbox_path(self, image_id: str) -> tuple[str, str]:
        manifest = await self._read_manifest() or {"images": []}
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        path = f"{self._root}/originals/{image_id}_{_safe_filename(entry['filename'])}"
        return path, entry.get("content_type", "application/octet-stream")

    async def async_list_images(self) -> list[LibraryImage]:
        manifest = await self._read_manifest() or {"images": []}
        return [LibraryImage.from_dict(d) for d in manifest.get("images", [])]

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        image_id = uuid.uuid4().hex[:12]
        path = f"{self._root}/originals/{image_id}_{_safe_filename(filename)}"
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/upload",
            headers=self._headers(
                {
                    "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite"}),
                    "Content-Type": "application/octet-stream",
                }
            ),
            data=raw_bytes,
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Dropbox upload failed ({resp.status}): {text[:200]}")

        record = LibraryImage(
            image_id=image_id,
            filename=filename,
            uploaded_at=time.time(),
            content_type=content_type,
            resolutions=[],
            albums=_normalize_albums(albums),
        )
        async with self._manifest_lock:
            manifest = await self._read_manifest() or {"images": []}
            manifest.setdefault("images", []).append(record.to_dict())
            await self._write_manifest(manifest)
        return record

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        path, content_type = await self._original_dropbox_path(image_id)
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/download",
            headers=self._headers({"Dropbox-API-Arg": json.dumps({"path": path})}),
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Dropbox download failed ({resp.status}): {text[:200]}")
        return await resp.read(), content_type

    async def _dropbox_download_bin(self, path: str) -> bytes | None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/download",
            headers=self._headers(
                {"Dropbox-API-Arg": json.dumps({"path": path})}
            ),
        )
        if resp.status in (404, 409):
            return None
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox bin download failed ({resp.status}): {text[:200]}"
            )
        return await resp.read()

    async def async_get_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> bytes | None:
        if codec_id:
            data = await self._dropbox_download_bin(
                self._bin_path(image_id, width, height, variant, codec_id)
            )
            if data is not None:
                return data
            return await self._dropbox_download_bin(
                self._bin_path(image_id, width, height, variant, "")
            )
        return await self._dropbox_download_bin(
            self._bin_path(image_id, width, height, variant, "")
        )

    async def async_save_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        data: bytes,
        variant: str = "",
        codec_id: str = "",
    ) -> None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/upload",
            headers=self._headers(
                {
                    "Dropbox-API-Arg": json.dumps(
                        {
                            "path": self._bin_path(
                                image_id, width, height, variant, codec_id
                            ),
                            "mode": "overwrite",
                        }
                    ),
                    "Content-Type": "application/octet-stream",
                }
            ),
            data=data,
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Dropbox bin upload failed ({resp.status}): {text[:200]}")

        async with self._manifest_lock:
            manifest = await self._read_manifest() or {"images": []}
            for d in manifest.get("images", []):
                if d["image_id"] == image_id:
                    resolutions = d.setdefault("resolutions", [])
                    if [width, height] not in resolutions:
                        resolutions.append([width, height])
                    break
            await self._write_manifest(manifest)

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest() or {"images": []}
            for d in manifest.get("images", []):
                if d["image_id"] == image_id:
                    d.update(fields)
                    break
            await self._write_manifest(manifest)

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest() or {"images": []}
            for d in manifest.get("images", []):
                fields = updates.get(d["image_id"])
                if fields:
                    d.update(fields)
            await self._write_manifest(manifest)

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        session = async_get_clientsession(self.hass)
        for variant in _ALL_BIN_VARIANTS:
            for codec_id in (*_known_codec_ids(), ""):
                resp = await session.post(
                    f"{_DROPBOX_API}/files/delete_v2",
                    headers=self._headers({"Content-Type": "application/json"}),
                    json={
                        "path": self._bin_path(
                            image_id, width, height, variant, codec_id
                        )
                    },
                )
                if resp.status >= 400 and resp.status not in (404, 409):
                    text = await resp.text()
                    raise LibraryBackendError(
                        f"Dropbox bin delete failed ({resp.status}): {text[:200]}"
                    )

    async def async_delete_image(self, image_id: str) -> None:
        session = async_get_clientsession(self.hass)
        path, _content_type = await self._original_dropbox_path(image_id)
        resp = await session.post(
            f"{_DROPBOX_API}/files/delete_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": path},
        )
        # Unlike async_delete_bin above, this response used to be discarded
        # unchecked -- a transient failure (expired token, rate limit, 5xx)
        # was treated as success and the manifest entry removed below
        # regardless, orphaning the file in the user's Dropbox with no
        # remaining record the app could ever reference or retry against.
        if resp.status >= 400 and resp.status not in (404, 409):
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox original delete failed ({resp.status}): {text[:200]}"
            )
        resp = await session.post(
            f"{_DROPBOX_API}/files/list_folder",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": f"{self._root}/bin", "recursive": True},
        )
        if resp.status < 400:
            data = await resp.json()
            for entry in data.get("entries", []):
                if entry.get(".tag") == "file" and entry.get("name") == f"{image_id}.bin":
                    await session.post(
                        f"{_DROPBOX_API}/files/delete_v2",
                        headers=self._headers({"Content-Type": "application/json"}),
                        json={"path": entry["path_lower"]},
                    )

        async with self._manifest_lock:
            manifest = await self._read_manifest() or {"images": []}
            manifest["images"] = [
                d for d in manifest.get("images", []) if d["image_id"] != image_id
            ]
            await self._write_manifest(manifest)

    async def async_discover_new_files(self) -> list[LibraryImage]:
        """Adopt any files sitting in the Dropbox inbox -- dropped
        there via Dropbox directly, not through Fraimic -- into the
        manifest, moving each through the same upload path a manual
        upload uses so it ends up in the normal originals/ layout."""
        session = async_get_clientsession(self.hass)

        # Make sure the inbox exists; a 409 here just means it already does.
        resp = await session.post(
            f"{_DROPBOX_API}/files/create_folder_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": self._inbox},
        )
        if resp.status >= 400 and resp.status != 409:
            text = await resp.text()
            raise LibraryBackendError(
                f"Couldn't prepare the Dropbox inbox folder ({resp.status}): {text[:200]}"
            )

        resp = await session.post(
            f"{_DROPBOX_API}/files/list_folder",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": self._inbox},
        )
        if resp.status == 409:
            return []  # a create/list race -- nothing to adopt yet
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(
                f"Couldn't list the Dropbox inbox folder ({resp.status}): {text[:200]}"
            )
        data = await resp.json()
        entries = [e for e in data.get("entries", []) if e.get(".tag") == "file"]

        adopted: list[LibraryImage] = []
        for entry in entries:
            path = entry["path_lower"]
            filename = entry["name"]
            try:
                dl_resp = await session.post(
                    f"{_DROPBOX_CONTENT_API}/files/download",
                    headers=self._headers({"Dropbox-API-Arg": json.dumps({"path": path})}),
                )
                if dl_resp.status >= 400:
                    text = await dl_resp.text()
                    raise LibraryBackendError(
                        f"Couldn't download '{filename}' ({dl_resp.status}): {text[:200]}"
                    )
                raw_bytes = await dl_resp.read()
                content_type = await self.hass.async_add_executor_job(
                    _detect_content_type, raw_bytes
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Dropbox discovery: failed to fetch '%s': %s", filename, err)
                continue

            record = await self.async_upload_original(filename, raw_bytes, content_type, [])

            del_resp = await session.post(
                f"{_DROPBOX_API}/files/delete_v2",
                headers=self._headers({"Content-Type": "application/json"}),
                json={"path": path},
            )
            if del_resp.status >= 400 and del_resp.status != 409:
                _LOGGER.warning(
                    "Dropbox discovery: adopted '%s' but couldn't remove it from the "
                    "inbox (%s) -- it may be re-discovered next time",
                    filename, del_resp.status,
                )

            adopted.append(record)

        return adopted

    async def async_get_local_path(self, image_id: str) -> str:
        cache_dir = self.hass.config.path(CACHE_DIRNAME)
        os.makedirs(cache_dir, exist_ok=True)
        
        manifest = await self.async_list_images()
        entry = next((img for img in manifest if img.image_id == image_id), None)
        filename = entry.filename if entry else f"{image_id}.jpg"
        ext = os.path.splitext(filename)[1] or ".jpg"
        
        cached_path = os.path.join(cache_dir, f"{image_id}{ext}")
        if os.path.isfile(cached_path):
            return cached_path
            
        data, _ = await self.async_get_original(image_id)
        await self.hass.async_add_executor_job(self._save_cached_file, cached_path, data)
        return cached_path

    def _save_cached_file(self, path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)


# ---------------------------------------------------------------------------
# Google Drive backend -- OAuth2 with a refresh token, obtained via the
# panel's "Connect Google Drive" flow (see library_http.py)
# ---------------------------------------------------------------------------

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
_GOOGLE_DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
_GOOGLE_LIBRARY_FOLDER_NAME = "Digital Frames Library"
_GOOGLE_LIBRARY_FOLDER_NAME_LEGACY = "Fraimic Library"
_GOOGLE_MANIFEST_NAME = "digital_frames_library_manifest.json"
_GOOGLE_MANIFEST_NAME_LEGACY = "fraimic_library_manifest.json"


class GoogleDriveLibraryBackend(LibraryBackend):
    """Stores the library in a "Digital Frames Library" folder in Drive.

    Uses the drive.file scope (the app can only see files it created). If a
    legacy "Fraimic Library" folder is already linked via settings, or still
    findable, that folder continues to be used so albums are not orphaned.
    """

    name = BACKEND_GOOGLE_DRIVE

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = dict(settings)
        self._access_token: str | None = None
        self._access_token_expires: float = 0.0
        # See LocalLibraryBackend._manifest_lock -- same read-modify-write
        # race, just over the Drive API instead of a local file.
        self._manifest_lock = asyncio.Lock()
        self._manifest_cache = _ManifestCache()

    async def async_setup(self) -> None:
        required = ("client_id", "client_secret", "refresh_token")
        missing = [k for k in required if not self.settings.get(k)]
        if missing:
            raise LibraryBackendError(
                "Google Drive isn't connected yet -- use 'Connect Google "
                "Drive' in the Library settings to authorize access."
            )
        await self._ensure_access_token(force=True)
        await self._ensure_folder()
        await self._ensure_manifest()

    async def _ensure_access_token(self, force: bool = False) -> None:
        if not force and self._access_token and time.time() < self._access_token_expires - 30:
            return
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": self.settings["client_id"],
                "client_secret": self.settings["client_secret"],
                "refresh_token": self.settings["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Google token refresh failed ({resp.status}): {text[:200]}")
        data = await resp.json()
        self._access_token = data["access_token"]
        self._access_token_expires = time.time() + data.get("expires_in", 3600)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if extra:
            headers.update(extra)
        return headers

    async def _find_app_folder(self, name: str) -> str | None:
        """Return id of an app-created folder with *name*, if any."""
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        # drive.file scope: list only sees files this app created.
        q = (
            f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        resp = await session.get(
            f"{_GOOGLE_DRIVE_API}/files",
            headers=self._headers(),
            params={"q": q, "spaces": "drive", "fields": "files(id,name)"},
        )
        if resp.status >= 400:
            return None
        files = (await resp.json()).get("files") or []
        return files[0]["id"] if files else None

    async def _ensure_folder(self) -> None:
        if self.settings.get("folder_id"):
            return
        # Prefer already-created legacy folder so albums stay put.
        for name in (_GOOGLE_LIBRARY_FOLDER_NAME_LEGACY, _GOOGLE_LIBRARY_FOLDER_NAME):
            found = await self._find_app_folder(name)
            if found:
                self.settings["folder_id"] = found
                if name == _GOOGLE_LIBRARY_FOLDER_NAME_LEGACY:
                    _LOGGER.info(
                        "Using existing Google Drive library folder %r", name
                    )
                return
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_GOOGLE_DRIVE_API}/files",
            headers=self._headers({"Content-Type": "application/json"}),
            json={
                "name": _GOOGLE_LIBRARY_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            },
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Couldn't create Drive folder ({resp.status}): {text[:200]}")
        data = await resp.json()
        self.settings["folder_id"] = data["id"]

    async def _ensure_manifest(self) -> None:
        if self.settings.get("manifest_file_id"):
            return
        # Prefer legacy manifest filename if present under this folder.
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        for name in (_GOOGLE_MANIFEST_NAME_LEGACY, _GOOGLE_MANIFEST_NAME):
            q = (
                f"name = '{name}' and '{self.settings['folder_id']}' in parents "
                "and trashed = false"
            )
            resp = await session.get(
                f"{_GOOGLE_DRIVE_API}/files",
                headers=self._headers(),
                params={"q": q, "spaces": "drive", "fields": "files(id,name)"},
            )
            if resp.status < 400:
                files = (await resp.json()).get("files") or []
                if files:
                    self.settings["manifest_file_id"] = files[0]["id"]
                    return
        manifest_id = await self._create_file(
            _GOOGLE_MANIFEST_NAME, b'{"images": []}', "application/json"
        )
        self.settings["manifest_file_id"] = manifest_id

    async def _create_file(self, name: str, content: bytes, mime_type: str) -> str:
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_GOOGLE_DRIVE_API}/files",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"name": name, "parents": [self.settings["folder_id"]]},
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Couldn't create Drive file '{name}' ({resp.status}): {text[:200]}")
        file_id = (await resp.json())["id"]
        await self._upload_content(file_id, content, mime_type)
        return file_id

    async def _upload_content(self, file_id: str, content: bytes, mime_type: str) -> None:
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.patch(
            f"{_GOOGLE_DRIVE_UPLOAD_API}/files/{file_id}?uploadType=media",
            headers=self._headers({"Content-Type": mime_type}),
            data=content,
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Drive upload failed ({resp.status}): {text[:200]}")

    async def _download_content(self, file_id: str) -> bytes | None:
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.get(
            f"{_GOOGLE_DRIVE_API}/files/{file_id}",
            headers=self._headers(),
            params={"alt": "media"},
        )
        if resp.status == 404:
            return None
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Drive download failed ({resp.status}): {text[:200]}")
        return await resp.read()

    async def _delete_file(self, file_id: str) -> None:
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.delete(f"{_GOOGLE_DRIVE_API}/files/{file_id}", headers=self._headers())
        # This response used to be discarded unchecked -- a transient
        # failure (expired token, rate limit, 5xx) was treated as success
        # and the manifest entry removed by the caller regardless,
        # orphaning the file in the user's Drive with no remaining record
        # the app could ever reference or retry against. 404 (already gone)
        # is not an error.
        if resp.status >= 400 and resp.status != 404:
            text = await resp.text()
            raise LibraryBackendError(f"Drive delete failed ({resp.status}): {text[:200]}")

    async def _read_manifest(self) -> dict[str, Any]:
        cached = self._manifest_cache.get()
        if cached is not None:
            return cached
        raw = await self._download_content(self.settings["manifest_file_id"])
        manifest = {"images": []} if raw is None else json.loads(raw.decode("utf-8"))
        self._manifest_cache.store(manifest)
        return manifest

    async def _write_manifest(self, manifest: dict[str, Any]) -> None:
        await self._upload_content(
            self.settings["manifest_file_id"],
            json.dumps(manifest).encode("utf-8"),
            "application/json",
        )
        self._manifest_cache.store(manifest)

    async def async_list_images(self) -> list[LibraryImage]:
        manifest = await self._read_manifest()
        return [LibraryImage.from_dict(d) for d in manifest.get("images", [])]

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        image_id = uuid.uuid4().hex[:12]
        file_id = await self._create_file(
            f"{image_id}_{_safe_filename(filename)}", raw_bytes, content_type
        )
        record_dict = {
            "image_id": image_id,
            "filename": filename,
            "uploaded_at": time.time(),
            "content_type": content_type,
            "resolutions": [],
            "albums": _normalize_albums(albums),
            "drive_file_id": file_id,
            "bin_file_ids": {},
        }
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            manifest.setdefault("images", []).append(record_dict)
            await self._write_manifest(manifest)
        return LibraryImage.from_dict(record_dict)

    def _find_entry(self, manifest: dict[str, Any], image_id: str) -> dict[str, Any]:
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        return entry

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        manifest = await self._read_manifest()
        entry = self._find_entry(manifest, image_id)
        data = await self._download_content(entry["drive_file_id"])
        if data is None:
            raise LibraryBackendError(f"Original for image '{image_id}' missing from Drive")
        return data, entry.get("content_type", "application/octet-stream")

    async def async_get_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        variant: str = "",
        codec_id: str = "",
    ) -> bytes | None:
        manifest = await self._read_manifest()
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            return None
        ids = entry.get("bin_file_ids", {})
        bin_file_id = ids.get(_bin_manifest_key(width, height, variant, codec_id))
        if not bin_file_id and codec_id:
            # Legacy pre-Phase-2 key (resolution only).
            bin_file_id = ids.get(_bin_manifest_key(width, height, variant, ""))
        if not bin_file_id:
            return None
        return await self._download_content(bin_file_id)

    async def async_save_bin(
        self,
        image_id: str,
        width: int,
        height: int,
        data: bytes,
        variant: str = "",
        codec_id: str = "",
    ) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            entry = self._find_entry(manifest, image_id)
            res_key = _bin_manifest_key(width, height, variant, codec_id)
            existing_id = entry.get("bin_file_ids", {}).get(res_key)
            if existing_id:
                await self._upload_content(existing_id, data, "application/octet-stream")
                return
            safe_name = res_key.replace("/", "_")
            file_id = await self._create_file(
                f"{image_id}_{safe_name}.bin", data, "application/octet-stream"
            )
            entry.setdefault("bin_file_ids", {})[res_key] = file_id
            if [width, height] not in entry.setdefault("resolutions", []):
                entry["resolutions"].append([width, height])
            await self._write_manifest(manifest)

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            entry = self._find_entry(manifest, image_id)
            entry.update(fields)
            await self._write_manifest(manifest)

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            for d in manifest.get("images", []):
                fields = updates.get(d["image_id"])
                if fields:
                    d.update(fields)
            await self._write_manifest(manifest)

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            entry = self._find_entry(manifest, image_id)
            bin_file_ids = entry.setdefault("bin_file_ids", {})
            for variant in _ALL_BIN_VARIANTS:
                for codec_id in (*_known_codec_ids(), ""):
                    res_key = _bin_manifest_key(width, height, variant, codec_id)
                    bin_file_id = bin_file_ids.get(res_key)
                    if bin_file_id:
                        # Delete on Drive first, persist the manifest only
                        # once it actually succeeds -- if a later variant's
                        # delete fails, everything deleted so far is already
                        # durably reflected and won't dangle-reference a
                        # file that no longer exists on a fresh manifest read.
                        await self._delete_file(bin_file_id)
                        bin_file_ids.pop(res_key, None)
                        await self._write_manifest(manifest)

    async def async_delete_image(self, image_id: str) -> None:
        async with self._manifest_lock:
            manifest = await self._read_manifest()
            entry = next(
                (d for d in manifest.get("images", []) if d["image_id"] == image_id),
                None,
            )
            if entry is None:
                return
            # Same ordering as async_delete_bin above: persist after each
            # successful delete so a later failure can't leave the manifest
            # referencing files already removed from Drive.
            if entry.get("drive_file_id"):
                await self._delete_file(entry["drive_file_id"])
                entry["drive_file_id"] = None
                await self._write_manifest(manifest)
            bin_file_ids = entry.setdefault("bin_file_ids", {})
            for res_key, bin_file_id in list(bin_file_ids.items()):
                await self._delete_file(bin_file_id)
                bin_file_ids.pop(res_key, None)
                await self._write_manifest(manifest)
            manifest["images"] = [
                d for d in manifest.get("images", []) if d["image_id"] != image_id
            ]
            await self._write_manifest(manifest)

    async def async_get_local_path(self, image_id: str) -> str:
        cache_dir = self.hass.config.path(CACHE_DIRNAME)
        os.makedirs(cache_dir, exist_ok=True)
        
        manifest = await self.async_list_images()
        entry = next((img for img in manifest if img.image_id == image_id), None)
        filename = entry.filename if entry else f"{image_id}.jpg"
        ext = os.path.splitext(filename)[1] or ".jpg"
        
        cached_path = os.path.join(cache_dir, f"{image_id}{ext}")
        if os.path.isfile(cached_path):
            return cached_path
            
        data, _ = await self.async_get_original(image_id)
        await self.hass.async_add_executor_job(self._save_cached_file, cached_path, data)
        return cached_path

    def _save_cached_file(self, path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)


# ---------------------------------------------------------------------------
# Manager -- backend-agnostic operations used by the HTTP views
# ---------------------------------------------------------------------------


class LibraryManager:
    """Owns the active backend and implements upload / send-from-library
    logic that's the same regardless of which backend is active."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _SETTINGS_STORAGE_VERSION, _SETTINGS_STORAGE_KEY)
        self._legacy_store: Store = Store(
            hass, _SETTINGS_STORAGE_VERSION, _LEGACY_SETTINGS_STORAGE_KEY
        )
        self._settings: dict[str, Any] = {"backend": BACKEND_LOCAL}
        self._backend: LibraryBackend = LocalLibraryBackend(hass)
        self._pending_google_oauth: dict[str, dict[str, Any]] = {}

        # Downscaled JPEG previews for the panel's grids, cached on local
        # disk keyed by image_id + edge -- local regardless of backend, since
        # image_ids are immutable (fresh uuid per upload, originals never
        # rewritten) a cached thumbnail can never go stale; entries are only
        # removed when the image itself is deleted.
        # Resolved after local backend migrate; interim path for early access.
        self._thumb_dir = hass.config.path(LIBRARY_DIRNAME, "thumbs")

        # .bin generation runs in the background instead of blocking whatever
        # triggered the upload (a manual upload, a scene pack install, or
        # discovery adopting an externally-added file) -- each entry is
        # either an image_id to backfill, or the sentinel below meaning
        # "sweep every image for any resolution it's missing". A single
        # worker processes this serially so concurrent triggers can't race
        # on the same manifest read-modify-write.
        self._backfill_pending: set[str] = set()
        self._backfill_task: asyncio.Task | None = None

    async def async_load(self) -> None:
        """Load persisted backend settings (if any) and stand up that backend.

        If this install was previously domain ``fraimic``, library backend
        settings live under the legacy store key — copy them forward so
        albums/backend choice survive the domain rename.
        """
        stored = await self._store.async_load()
        if not stored:
            legacy = await self._legacy_store.async_load()
            if legacy:
                stored = legacy
                await self._store.async_save(legacy)
                _LOGGER.info(
                    "Migrated library settings from %s → %s",
                    _LEGACY_SETTINGS_STORAGE_KEY,
                    _SETTINGS_STORAGE_KEY,
                )
        if stored:
            self._settings = stored
        self._backend = self._build_backend(self._settings)
        try:
            await self._backend.async_setup()
        except LibraryBackendError as err:
            _LOGGER.warning(
                "Configured library backend '%s' failed to initialise (%s); "
                "falling back to local storage",
                self._settings.get("backend"),
                err,
            )
            self._settings = {"backend": BACKEND_LOCAL}
            self._backend = LocalLibraryBackend(self.hass)
            await self._backend.async_setup()
        else:
            # Some backends (Google Drive) fill in extra bookkeeping fields
            # -- folder/manifest ids -- the first time they run. Persist
            # those back so we don't recreate them on every restart.
            backend_settings = getattr(self._backend, "settings", self._settings)
            if backend_settings != self._settings:
                self._settings = backend_settings
                await self._store.async_save(self._settings)

        # Thumbs live under the local library root (post-rename if migrated).
        if isinstance(self._backend, LocalLibraryBackend):
            self._thumb_dir = os.path.join(self._backend._root, "thumbs")
        else:
            # Cloud backends still cache thumbs locally under the product path.
            root = _migrate_local_dirname(
                self.hass, new=LIBRARY_DIRNAME, legacy=LEGACY_LIBRARY_DIRNAME
            )
            self._thumb_dir = os.path.join(root, "thumbs")
        # Bin/decode cache rename (optional; missing is fine).
        await self.hass.async_add_executor_job(
            lambda: _migrate_local_dirname(
                self.hass, new=CACHE_DIRNAME, legacy=LEGACY_CACHE_DIRNAME
            )
        )

    def _build_backend(self, settings: dict[str, Any]) -> LibraryBackend:
        backend_type = settings.get("backend", BACKEND_LOCAL)
        if backend_type == BACKEND_GOOGLE_DRIVE:
            return GoogleDriveLibraryBackend(self.hass, settings)
        if backend_type == BACKEND_DROPBOX:
            return DropboxLibraryBackend(self.hass, settings)
        return LocalLibraryBackend(self.hass)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def ai_auto_tagging(self) -> bool:
        """Return whether AI auto-tagging is enabled for uploads."""
        return self._settings.get("ai_auto_tagging", False)

    async def async_set_ai_auto_tagging(self, enabled: bool) -> None:
        """Enable or disable AI auto-tagging."""
        self._settings["ai_auto_tagging"] = bool(enabled)
        await self._store.async_save(self._settings)

    async def async_set_backend(self, settings: dict[str, Any]) -> None:
        """Validate then switch backends; only persists on success."""
        candidate = self._build_backend(settings)
        await candidate.async_setup()  # raises LibraryBackendError on failure
        self._backend = candidate
        # async_setup() may have filled in extra bookkeeping fields (Drive's
        # folder/manifest ids); persist whatever the backend ended up with,
        # not just the caller's original input.
        self._settings = getattr(candidate, "settings", settings)
        await self._store.async_save(self._settings)

    def google_redirect_uri(self) -> str | None:
        """The fixed redirect URI Google sends the OAuth code back to."""
        external_url = self.hass.config.external_url
        if not external_url:
            return None
        return external_url.rstrip("/") + "/api/digital_frames/library/oauth/google/callback"

    def create_pending_google_oauth(self, client_id: str, client_secret: str) -> str:
        """Stash client_id/secret for a few minutes while the user completes
        Google's consent screen, keyed by a one-time state token."""
        state = uuid.uuid4().hex
        self._pending_google_oauth[state] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "expires": time.time() + 600,
        }
        return state

    def pop_pending_google_oauth(self, state: str) -> dict[str, Any] | None:
        entry = self._pending_google_oauth.pop(state, None)
        if entry is None:
            return None
        if time.time() > entry["expires"]:
            return None
        return entry

    async def async_list_images(self) -> list[dict[str, Any]]:
        images = await self._backend.async_list_images()
        return [img.to_dict() for img in images]

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        return await self._backend.async_get_original(image_id)

    async def async_get_local_path(self, image_id: str) -> str:
        return await self._backend.async_get_local_path(image_id)

    # -- thumbnails (local disk cache, backend-agnostic) --

    def _thumb_path(self, image_id: str, edge: int) -> str:
        image_id = _safe_image_id(image_id)
        return os.path.join(self._thumb_dir, f"{image_id}_{edge}.jpg")

    def _read_thumbnail_sync(self, path: str) -> bytes | None:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _write_thumbnail_sync(self, path: str, raw_bytes: bytes, edge: int) -> bytes:
        from .image_converter import make_thumbnail  # noqa: PLC0415

        thumb = make_thumbnail(raw_bytes, edge)
        os.makedirs(self._thumb_dir, exist_ok=True)
        # Unique temp name: two concurrent requests for the same not-yet-
        # cached image must not race on one shared .tmp file.
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "wb") as f:
            f.write(thumb)
        os.replace(tmp, path)
        return thumb

    def _purge_thumbnails_sync(self, image_id: str) -> None:
        if not os.path.isdir(self._thumb_dir):
            return
        prefix = f"{image_id}_"
        for fn in os.listdir(self._thumb_dir):
            if fn.startswith(prefix):
                try:
                    os.remove(os.path.join(self._thumb_dir, fn))
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass

    async def async_get_thumbnail(self, image_id: str, edge: int) -> bytes:
        """A downscaled JPEG of the original, generated on first request and
        cached on local disk -- even when the originals live in Dropbox or
        Google Drive, so grid loads never re-download from the cloud."""
        path = self._thumb_path(image_id, edge)
        cached = await self.hass.async_add_executor_job(self._read_thumbnail_sync, path)
        if cached is not None:
            return cached
        raw_bytes, _content_type = await self._backend.async_get_original(image_id)
        return await self.hass.async_add_executor_job(
            self._write_thumbnail_sync, path, raw_bytes, edge
        )

    async def async_upload(
        self, filename: str, raw_bytes: bytes, albums: list[str] | None = None
    ) -> dict[str, Any]:
        """Store the original and return immediately -- .bin generation for
        every configured frame resolution happens in the background (see
        _schedule_backfill) instead of blocking the caller. A "Send" issued
        before backfill finishes still works: async_get_bin_for_send
        generates on the fly if the cache isn't warm yet."""
        content_type = await self.hass.async_add_executor_job(
            _detect_content_type, raw_bytes
        )
        record = await self._backend.async_upload_original(
            filename, raw_bytes, content_type, _normalize_albums(albums)
        )
        self._schedule_backfill(record.image_id)
        self._schedule_auto_tagging(record.image_id)
        return record.to_dict()

    async def async_discover(self) -> dict[str, Any]:
        """Adopt files added to the backend outside of Fraimic (e.g.
        dropped straight into Dropbox) into the manifest, then queue a full
        backfill sweep to generate .bin files for them (and for anything
        else left incomplete by an earlier interrupted install/upload)."""
        if not getattr(self._backend, "supports_discovery", False):
            raise LibraryBackendError(
                f"Discovery isn't supported for the '{self._backend.name}' backend."
            )
        discovered = await self._backend.async_discover_new_files()
        self._schedule_backfill(_BACKFILL_SWEEP_ALL)
        for img in discovered:
            self._schedule_auto_tagging(img.image_id)
        return {
            "success": True,
            "discovered": len(discovered),
            "images": [img.to_dict() for img in discovered],
        }

    def _schedule_backfill(self, item: str) -> None:
        """Queue an image_id (or _BACKFILL_SWEEP_ALL) for background .bin
        generation and make sure exactly one worker is running for it."""
        self._backfill_pending.add(item)
        if self._backfill_task is None or self._backfill_task.done():
            self._backfill_task = self.hass.async_create_task(self._async_backfill_worker())

    async def _async_backfill_worker(self) -> None:
        while self._backfill_pending:
            item = self._backfill_pending.pop()
            try:
                if item == _BACKFILL_SWEEP_ALL:
                    for image in await self._backend.async_list_images():
                        await self._backfill_one(image)
                else:
                    image = await self._find_image(item)
                    if image is not None:
                        await self._backfill_one(image)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Library backfill failed for '%s': %s", item, err)

    async def _backfill_one(self, record: LibraryImage) -> None:
        """Generate whatever wire payloads `record` is missing for the
        frames currently configured (Spectra .bin or Meural JPEG)."""
        # has_resolution is still geometry-only (legacy manifest field);
        # missing means we have no cached payload for that size yet.
        missing = [
            (spec, codec_id)
            for spec, codec_id in _all_render_targets(self.hass)
            if not record.has_resolution(spec.width, spec.height)
        ]
        if not missing:
            return

        try:
            raw_bytes, _content_type = await self._backend.async_get_original(record.image_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Backfill: couldn't fetch original for '%s': %s", record.image_id, err
            )
            return

        from .panel_codec import encode_for_panel  # noqa: PLC0415

        for spec, codec_id in missing:
            try:
                bin_bytes = await self.hass.async_add_executor_job(
                    encode_for_panel,
                    raw_bytes,
                    spec.width,
                    spec.height,
                    spec.rotation,
                    spec.locked,
                    "fast",
                    None,
                    codec_id,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Failed converting library image %s to %dx%d (%s): %s",
                    record.image_id, spec.width, spec.height, codec_id, err,
                )
                continue
            await self._backend.async_save_bin(
                record.image_id,
                spec.width,
                spec.height,
                bin_bytes,
                spec.variant,
                codec_id,
            )

    async def _find_image(self, image_id: str) -> LibraryImage | None:
        images = await self._backend.async_list_images()
        return next((img for img in images if img.image_id == image_id), None)

    async def async_get_bin_for_send(
        self,
        image_id: str,
        spec: RenderSpec,
        pack_method: str | None = None,
        codec_id: str | None = None,
        crop_box_override: tuple[float, ...] | list[float] | None = None,
    ) -> bytes:
        """Return a cached .bin for this render spec, generating + caching it
        on the fly if this render hasn't been seen for this image before
        (e.g. a frame added after the image was uploaded, or a crop was just
        changed and invalidated the old cache). Uses the image's saved manual
        crop for the spec's effective resolution if one exists; otherwise
        falls back to the automatic render (centered cover-crop when locked,
        sideways-rotate-to-fill when not).

        Cache keys include *codec_id* (PanelCodec — FramePort Phase 2). When
        omitted, the codec is resolved from the target resolution's frame
        type. Callers that have a config entry should pass
        ``panel_codec_for_entry(entry).id`` so size-based codec wins over
        geometry alone.

        pack_method ("legacy" | "fast"), when given, is an A/B testing
        override: the .bin cache is bypassed entirely -- no read (so the
        requested method definitely runs) and no write (so a test send never
        pollutes the cache) -- and the conversion packs with that method.
        None (the normal path) converts with the default packer and uses the
        cache as usual.

        crop_box_override, when given, wins outright over the image's saved
        manual crop (record.crops) and -- like pack_method above -- bypasses
        the .bin cache entirely, both read and write. This is required, not
        an optimization: record.crops is keyed only by "WxH", one crop per
        resolution, so it can't represent two same-resolution frames (e.g.
        a wall-banner message split across two identical frames) wanting
        different crops of the same saved image. Caching keyed on
        image+resolution+codec alone would let the second frame's send
        silently read back the first frame's crop. Used by the scene
        mapping type {"type": "image_crop", ...} (see scenes.py); never set
        by the ordinary manual-crop editor path."""
        width, height = spec.width, spec.height
        if not codec_id:
            from .frame_types import codec_id_for_resolution  # noqa: PLC0415

            try:
                codec_id = codec_id_for_resolution(width, height)
            except ValueError as err:
                raise LibraryBackendError(
                    f"No panel codec for {width}x{height}; pass codec_id explicitly "
                    f"(e.g. Meural JPEG frames)"
                ) from err

        if pack_method is None and crop_box_override is None:
            cached = await self._backend.async_get_bin(
                image_id, width, height, spec.variant, codec_id
            )
            if cached is not None:
                return cached

        raw_bytes, _content_type = await self._backend.async_get_original(image_id)
        if crop_box_override is not None:
            crop_box = tuple(crop_box_override)
        else:
            record = await self._find_image(image_id)
            crop_box = (record.crops if record else {}).get(f"{width}x{height}")
            if not crop_box and record and record.crops:
                fallback_key = "portrait" if width < height else "landscape"
                crop_box = record.crops.get(fallback_key)
        effective_method = pack_method or "fast"

        # PanelCodec seam: resolution selects split-half vs sequential (7.3")
        # packing. Do not call image_converter from here — encode_for_panel is
        # the single library encode entry (docs/FRAME_PORT.md Phase 1).
        from .panel_codec import encode_for_panel  # noqa: PLC0415

        bin_bytes = await self.hass.async_add_executor_job(
            encode_for_panel,
            raw_bytes,
            width,
            height,
            spec.rotation,
            spec.locked,
            effective_method,
            tuple(crop_box) if crop_box else None,
            codec_id,
        )
        if pack_method is None and crop_box_override is None:
            await self._backend.async_save_bin(
                image_id, width, height, bin_bytes, spec.variant, codec_id
            )
        return bin_bytes

    async def async_set_crop(
        self, image_id: str, width: int | str, height: int, crop_box: list[float]
    ) -> dict[str, Any]:
        """Persist a manual crop rectangle for one image at one resolution or orientation,
        and drop any cached .bin for that resolution so the next send picks
        up the new crop instead of a stale render."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        crops = dict(record.crops)
        if isinstance(width, str) and width in ("portrait", "landscape"):
            crops[width] = [float(v) for v in crop_box]
            # Clear cached bins for all resolutions matching this orientation
            from .frame_types import FRAME_TYPES  # noqa: PLC0415
            for ft in FRAME_TYPES.values():
                w, h = ft.resolution
                for rw, rh in ((w, h), (h, w)):
                    is_port = rw < rh
                    is_land = rw >= rh
                    if (width == "portrait" and is_port) or (width == "landscape" and is_land):
                        try:
                            await self._backend.async_delete_bin(image_id, rw, rh)
                        except Exception:  # noqa: BLE001
                            pass
        else:
            crops[f"{width}x{height}"] = [float(v) for v in crop_box]
            # Also update the fallback orientation crop box!
            # If the user saved a crop for a specific resolution, we also copy it
            # to the corresponding generic orientation key, so that other frames of the same
            # orientation immediately pick it up as a default fallback crop.
            orient_key = "portrait" if width < height else "landscape"
            crops[orient_key] = [float(v) for v in crop_box]

            await self._backend.async_delete_bin(image_id, width, height)
            # Delete other resolutions matching this orientation since we updated the fallback
            from .frame_types import FRAME_TYPES  # noqa: PLC0415
            for ft in FRAME_TYPES.values():
                w, h = ft.resolution
                for rw, rh in ((w, h), (h, w)):
                    if rw == width and rh == height:
                        continue
                    is_port = rw < rh
                    is_land = rw >= rh
                    if (orient_key == "portrait" and is_port) or (orient_key == "landscape" and is_land):
                        try:
                            await self._backend.async_delete_bin(image_id, rw, rh)
                        except Exception:  # noqa: BLE001
                            pass

        await self._backend.async_update_image_fields(image_id, crops=crops)
        record.crops = crops
        return record.to_dict()

    async def async_clear_crop(
        self, image_id: str, width: int | str, height: int
    ) -> dict[str, Any]:
        """Revert to the automatic (centered cover-crop) rendering
        for one image at one resolution or orientation."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        crops = dict(record.crops)
        if isinstance(width, str) and width in ("portrait", "landscape"):
            crops.pop(width, None)
            from .frame_types import FRAME_TYPES  # noqa: PLC0415
            for ft in FRAME_TYPES.values():
                w, h = ft.resolution
                for rw, rh in ((w, h), (h, w)):
                    is_port = rw < rh
                    is_land = rw >= rh
                    if (width == "portrait" and is_port) or (width == "landscape" and is_land):
                        try:
                            await self._backend.async_delete_bin(image_id, rw, rh)
                        except Exception:  # noqa: BLE001
                            pass
        else:
            crops.pop(f"{width}x{height}", None)
            await self._backend.async_delete_bin(image_id, width, height)

        await self._backend.async_update_image_fields(image_id, crops=crops)
        record.crops = crops
        return record.to_dict()

    async def async_delete(self, image_id: str) -> None:
        await self._backend.async_delete_image(image_id)
        await self.hass.async_add_executor_job(self._purge_thumbnails_sync, image_id)

    async def async_list_albums(self) -> list[dict[str, Any]]:
        """Every distinct album tag in use, with a photo count and a cover
        image (the most recently uploaded photo carrying that tag). Always
        includes the default album even if it's currently empty."""
        images = await self._backend.async_list_images()
        by_name: dict[str, list[LibraryImage]] = {DEFAULT_ALBUM: []}
        for img in images:
            for name in img.albums:
                by_name.setdefault(name, []).append(img)

        albums = []
        for name, members in by_name.items():
            cover = max(members, key=lambda i: i.uploaded_at) if members else None
            albums.append(
                {
                    "name": name,
                    "count": len(members),
                    "cover_image_id": cover.image_id if cover else None,
                }
            )
        albums.sort(key=lambda a: (a["name"] != DEFAULT_ALBUM, a["name"].lower()))
        return albums

    async def async_set_image_albums(
        self, image_id: str, albums: list[str]
    ) -> dict[str, Any]:
        """Replace the full set of album tags on one image."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        normalized = _normalize_albums(albums)
        await self._backend.async_update_image_fields(image_id, albums=normalized)
        record.albums = normalized
        return record.to_dict()

    async def async_set_image_voice_name(
        self, image_id: str, voice_name: str | None
    ) -> dict[str, Any]:
        """Update the voice name of one image."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        vname = voice_name.strip() if voice_name else None
        await self._backend.async_update_image_fields(image_id, voice_name=vname)
        record.voice_name = vname
        return record.to_dict()

    async def async_set_image_tags(
        self, image_id: str, tags: list[str] | None
    ) -> dict[str, Any]:
        """Update the tags of one image."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        normalized = _normalize_tags(tags)
        await self._backend.async_update_image_fields(image_id, tags=normalized)
        record.tags = normalized
        return record.to_dict()

    async def _async_apply_album_transform(
        self, transform: Callable[[LibraryImage], list[str]]
    ) -> dict[str, dict[str, Any]]:
        """Build a bulk-update dict by applying `transform` to every image's
        current album list, keeping only the images it actually changes.
        Shared by every album-membership mutation (add/rename/delete) so
        they all funnel through one manifest read + one bulk write."""
        images = await self._backend.async_list_images()
        updates: dict[str, dict[str, Any]] = {}
        for img in images:
            new_albums = _normalize_albums(transform(img))
            if new_albums != img.albums:
                updates[img.image_id] = {"albums": new_albums}
        return updates

    async def async_add_images_to_album(
        self, image_ids: list[str], album_name: str
    ) -> int:
        """Tag a batch of existing images with an album in one manifest
        round-trip. A fresh (not-yet-used) name is all "creating" an album
        takes -- albums are emergent from tags, not a separate registry."""
        album_name = (album_name or "").strip()
        if not album_name:
            raise LibraryBackendError("Album name can't be empty")

        id_set = {i for i in (image_ids or []) if i}
        if not id_set:
            raise LibraryBackendError("Select at least one photo")

        updates = await self._async_apply_album_transform(
            lambda img: [*img.albums, album_name] if img.image_id in id_set else img.albums
        )
        if updates:
            await self._backend.async_bulk_update_image_fields(updates)
        return len(updates)

    async def async_rename_album(self, old_name: str, new_name: str) -> int:
        """Rename an album tag across every image that carries it. Returns
        how many images were affected."""
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if old_name == DEFAULT_ALBUM:
            raise LibraryBackendError(f"The default album '{DEFAULT_ALBUM}' can't be renamed")
        if not old_name or not new_name:
            raise LibraryBackendError("Album names can't be empty")
        if new_name == DEFAULT_ALBUM:
            raise LibraryBackendError(
                f"Can't rename an album to the default album '{DEFAULT_ALBUM}' -- "
                "use the album picker to add individual photos to it instead"
            )

        updates = await self._async_apply_album_transform(
            lambda img: [new_name if a == old_name else a for a in img.albums]
        )
        if updates:
            await self._backend.async_bulk_update_image_fields(updates)
        return len(updates)

    async def async_delete_album(self, name: str) -> int:
        """Remove an album tag from every image that carries it (the images
        themselves are never deleted). Returns how many images were
        affected."""
        name = (name or "").strip()
        if name == DEFAULT_ALBUM:
            raise LibraryBackendError(f"The default album '{DEFAULT_ALBUM}' can't be deleted")
        if not name:
            raise LibraryBackendError("Album name can't be empty")

        updates = await self._async_apply_album_transform(
            lambda img: [a for a in img.albums if a != name]
        )
        if updates:
            await self._backend.async_bulk_update_image_fields(updates)
        return len(updates)

    def _find_ai_task_tagging_entity(self) -> str | None:
        """Return the first ai_task entity that supports data generation and attachments."""
        for state in self.hass.states.async_all("ai_task"):
            features = state.attributes.get("supported_features", 0)
            if (features & 1) and (features & 2):
                return state.entity_id
        return None

    def _schedule_auto_tagging(self, image_id: str, force: bool = False) -> None:
        """Queue auto-tagging for an image."""
        self.hass.async_create_task(self.async_auto_tag_image(image_id, force=force))

    async def async_auto_tag_image(self, image_id: str, force: bool = False) -> None:
        """Analyze the image using the default AI Task entity and add tags."""
        if not force and not self.ai_auto_tagging:
            _LOGGER.debug("AI auto-tagging is not enabled in Fraimic settings")
            return

        ai_task_entity = self._find_ai_task_tagging_entity()
        if not ai_task_entity:
            _LOGGER.debug(
                "No AI Task entity supporting data generation and attachments is configured"
            )
            return

        images = await self.async_list_images()
        record = next((img for img in images if img.get("image_id") == image_id), None)
        if not record:
            _LOGGER.warning("Image '%s' not found for auto-tagging", image_id)
            return

        media_content_id = f"media-source://{DOMAIN}/image/{image_id}"

        prompt = (
            "Analyze the attached image and generate relevant tags (comma-separated, lowercase). "
            "Describe the artist/creator if known, the subject matter, the setting/scenery (e.g. beach, forest), "
            "prominent colors, style, objects, and people. "
            "Return ONLY a comma-separated list of tags, nothing else."
        )

        _LOGGER.info("Requesting auto-tags for image '%s' using %s", image_id, ai_task_entity)

        try:
            result = await self.hass.services.async_call(
                "ai_task",
                "generate_data",
                {
                    "entity_id": ai_task_entity,
                    "task_name": "Digital Frames auto-tagging",
                    "instructions": prompt,
                    "attachments": [
                        {
                            "media_content_id": media_content_id,
                            "media_content_type": record.get("content_type", "image/png"),
                        }
                    ],
                },
                blocking=True,
                return_response=True,
            )

            raw_text = result.get("data", "")
            if not raw_text:
                _LOGGER.warning("AI Task returned no data for image '%s'", image_id)
                return

            generated_tags = [t.strip().lower() for t in raw_text.split(",") if t.strip()]
            if generated_tags:
                _LOGGER.info("Generated tags for '%s': %s", image_id, generated_tags)
                existing_tags = record.get("tags") or []
                merged_tags = list(dict.fromkeys(existing_tags + generated_tags))
                await self.async_set_image_tags(image_id, merged_tags)
        except Exception as err:
            _LOGGER.exception("Failed to auto-tag image '%s': %s", image_id, err)

