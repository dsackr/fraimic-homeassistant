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

from .const import CONF_HEIGHT, CONF_WIDTH, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SETTINGS_STORAGE_KEY = f"{DOMAIN}_library_settings"
_SETTINGS_STORAGE_VERSION = 1

BACKEND_LOCAL = "local"
BACKEND_GOOGLE_DRIVE = "google_drive"
BACKEND_DROPBOX = "dropbox"

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


def _all_frame_resolutions(hass: "HomeAssistant") -> set[tuple[int, int]]:
    """Distinct (width, height) pairs across every configured Fraimic frame."""
    resolutions: set[tuple[int, int]] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        width = entry.data.get(CONF_WIDTH)
        height = entry.data.get(CONF_HEIGHT)
        if isinstance(width, int) and isinstance(height, int):
            resolutions.add((width, height))
    return resolutions


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:128] or "image"


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
    # resolution yet (falls back to the automatic letterbox render).
    crops: dict[str, list[float]] = field(default_factory=dict)
    # Album tags this image belongs to. Not folders -- an image can carry
    # any number of these with no duplication of the underlying file.
    albums: list[str] = field(default_factory=lambda: [DEFAULT_ALBUM])

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
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        raise NotImplementedError

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
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
        """Remove a cached .bin for one resolution so it regenerates on next send."""
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


# ---------------------------------------------------------------------------
# Local (HA-server) backend -- fully implemented
# ---------------------------------------------------------------------------


class LocalLibraryBackend(LibraryBackend):
    """Stores the library under <config>/fraimic_library/ on the HA host."""

    name = BACKEND_LOCAL

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self.settings: dict[str, Any] = {"backend": BACKEND_LOCAL}
        self._root = hass.config.path("fraimic_library")
        self._manifest_path = os.path.join(self._root, "manifest.json")

    async def async_setup(self) -> None:
        await self.hass.async_add_executor_job(self._ensure_dirs)

    # -- sync helpers (always run via executor) --

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

    def _bin_path(self, image_id: str, width: int, height: int) -> str:
        return os.path.join(self._root, "bin", f"{width}x{height}", f"{image_id}.bin")

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
        path = self._find_original_path(image_id)
        if path is None:
            raise LibraryBackendError(f"Original for image '{image_id}' not found")
        with open(path, "rb") as f:
            return f.read(), content_type

    def _get_bin_sync(self, image_id: str, width: int, height: int) -> bytes | None:
        path = self._bin_path(image_id, width, height)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _save_bin_sync(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        path = self._bin_path(image_id, width, height)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        manifest = self._read_manifest()
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                resolutions = d.setdefault("resolutions", [])
                if [width, height] not in resolutions:
                    resolutions.append([width, height])
                break
        self._write_manifest(manifest)

    def _delete_image_sync(self, image_id: str) -> None:
        path = self._find_original_path(image_id)
        if path and os.path.isfile(path):
            os.remove(path)
        bin_root = os.path.join(self._root, "bin")
        if os.path.isdir(bin_root):
            for res_dir in os.listdir(bin_root):
                candidate = os.path.join(bin_root, res_dir, f"{image_id}.bin")
                if os.path.isfile(candidate):
                    os.remove(candidate)
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
        path = self._bin_path(image_id, width, height)
        if os.path.isfile(path):
            os.remove(path)

    # -- async public API --

    async def async_list_images(self) -> list[LibraryImage]:
        return await self.hass.async_add_executor_job(self._list_images_sync)

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        return await self.hass.async_add_executor_job(self._get_original_sync, image_id)

    async def async_get_bin(
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(
            self._get_bin_sync, image_id, width, height
        )

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        await self.hass.async_add_executor_job(
            self._save_bin_sync, image_id, width, height, data
        )

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        await self.hass.async_add_executor_job(
            self._update_image_fields_sync, image_id, fields
        )

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
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
        return await self.hass.async_add_executor_job(
            self._upload_original_sync, filename, raw_bytes, content_type, albums
        )

    async def async_delete_image(self, image_id: str) -> None:
        await self.hass.async_add_executor_job(self._delete_image_sync, image_id)


# ---------------------------------------------------------------------------
# Dropbox backend -- a single long-lived access token, pasted in by the user
# ---------------------------------------------------------------------------

_DROPBOX_API = "https://api.dropboxapi.com/2"
_DROPBOX_CONTENT_API = "https://content.dropboxapi.com/2"
_DROPBOX_ROOT = "/fraimic_library"
_DROPBOX_MANIFEST_PATH = f"{_DROPBOX_ROOT}/manifest.json"
# Files dropped here (via Dropbox's own app/website, outside Fraimic) are
# adopted into the manifest by async_discover_new_files() and moved into
# the normal originals/ layout -- kept separate from originals/ itself so
# discovery never has to guess which files there are "ours" vs. new.
_DROPBOX_INBOX = f"{_DROPBOX_ROOT}/inbox"


class DropboxLibraryBackend(LibraryBackend):
    """Stores the library in the user's Dropbox under /fraimic_library.

    Auth is a single long-lived access token generated by the user in the
    Dropbox App Console -- no OAuth redirect dance needed.
    """

    name = BACKEND_DROPBOX
    supports_discovery = True

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = dict(settings)
        self._access_token = (self.settings.get("access_token") or "").strip()

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
        await self._ensure_manifest()

    async def _ensure_manifest(self) -> None:
        manifest = await self._read_manifest()
        if manifest is None:
            await self._write_manifest({"images": []})

    async def _read_manifest(self) -> dict[str, Any] | None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/download",
            headers=self._headers(
                {"Dropbox-API-Arg": json.dumps({"path": _DROPBOX_MANIFEST_PATH})}
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
                        {"path": _DROPBOX_MANIFEST_PATH, "mode": "overwrite"}
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

    def _bin_path(self, image_id: str, width: int, height: int) -> str:
        return f"{_DROPBOX_ROOT}/bin/{width}x{height}/{image_id}.bin"

    async def _original_dropbox_path(self, image_id: str) -> tuple[str, str]:
        manifest = await self._read_manifest() or {"images": []}
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        path = f"{_DROPBOX_ROOT}/originals/{image_id}_{_safe_filename(entry['filename'])}"
        return path, entry.get("content_type", "application/octet-stream")

    async def async_list_images(self) -> list[LibraryImage]:
        manifest = await self._read_manifest() or {"images": []}
        return [LibraryImage.from_dict(d) for d in manifest.get("images", [])]

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str, albums: list[str]
    ) -> LibraryImage:
        image_id = uuid.uuid4().hex[:12]
        path = f"{_DROPBOX_ROOT}/originals/{image_id}_{_safe_filename(filename)}"
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

    async def async_get_bin(
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/download",
            headers=self._headers(
                {"Dropbox-API-Arg": json.dumps({"path": self._bin_path(image_id, width, height)})}
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

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_CONTENT_API}/files/upload",
            headers=self._headers(
                {
                    "Dropbox-API-Arg": json.dumps(
                        {"path": self._bin_path(image_id, width, height), "mode": "overwrite"}
                    ),
                    "Content-Type": "application/octet-stream",
                }
            ),
            data=data,
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Dropbox bin upload failed ({resp.status}): {text[:200]}")

        manifest = await self._read_manifest() or {"images": []}
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                resolutions = d.setdefault("resolutions", [])
                if [width, height] not in resolutions:
                    resolutions.append([width, height])
                break
        await self._write_manifest(manifest)

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        manifest = await self._read_manifest() or {"images": []}
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                d.update(fields)
                break
        await self._write_manifest(manifest)

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        manifest = await self._read_manifest() or {"images": []}
        for d in manifest.get("images", []):
            fields = updates.get(d["image_id"])
            if fields:
                d.update(fields)
        await self._write_manifest(manifest)

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_DROPBOX_API}/files/delete_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": self._bin_path(image_id, width, height)},
        )
        if resp.status >= 400 and resp.status not in (404, 409):
            text = await resp.text()
            raise LibraryBackendError(
                f"Dropbox bin delete failed ({resp.status}): {text[:200]}"
            )

    async def async_delete_image(self, image_id: str) -> None:
        session = async_get_clientsession(self.hass)
        path, _content_type = await self._original_dropbox_path(image_id)
        await session.post(
            f"{_DROPBOX_API}/files/delete_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": path},
        )
        resp = await session.post(
            f"{_DROPBOX_API}/files/list_folder",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": f"{_DROPBOX_ROOT}/bin", "recursive": True},
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

        manifest = await self._read_manifest() or {"images": []}
        manifest["images"] = [
            d for d in manifest.get("images", []) if d["image_id"] != image_id
        ]
        await self._write_manifest(manifest)

    async def async_discover_new_files(self) -> list[LibraryImage]:
        """Adopt any files sitting in /fraimic_library/inbox -- dropped
        there via Dropbox directly, not through Fraimic -- into the
        manifest, moving each through the same upload path a manual
        upload uses so it ends up in the normal originals/ layout."""
        session = async_get_clientsession(self.hass)

        # Make sure the inbox exists; a 409 here just means it already does.
        resp = await session.post(
            f"{_DROPBOX_API}/files/create_folder_v2",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": _DROPBOX_INBOX},
        )
        if resp.status >= 400 and resp.status != 409:
            text = await resp.text()
            raise LibraryBackendError(
                f"Couldn't prepare the Dropbox inbox folder ({resp.status}): {text[:200]}"
            )

        resp = await session.post(
            f"{_DROPBOX_API}/files/list_folder",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"path": _DROPBOX_INBOX},
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


# ---------------------------------------------------------------------------
# Google Drive backend -- OAuth2 with a refresh token, obtained via the
# panel's "Connect Google Drive" flow (see library_http.py)
# ---------------------------------------------------------------------------

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
_GOOGLE_DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
_GOOGLE_LIBRARY_FOLDER_NAME = "Fraimic Library"
_GOOGLE_MANIFEST_NAME = "fraimic_library_manifest.json"


class GoogleDriveLibraryBackend(LibraryBackend):
    """Stores the library in a "Fraimic Library" folder in the user's
    Google Drive, using the drive.file scope (the app can only see files it
    created -- never the user's whole Drive).
    """

    name = BACKEND_GOOGLE_DRIVE

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = dict(settings)
        self._access_token: str | None = None
        self._access_token_expires: float = 0.0

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

    async def _ensure_folder(self) -> None:
        if self.settings.get("folder_id"):
            return
        await self._ensure_access_token()
        session = async_get_clientsession(self.hass)
        resp = await session.post(
            f"{_GOOGLE_DRIVE_API}/files",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"name": _GOOGLE_LIBRARY_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        )
        if resp.status >= 400:
            text = await resp.text()
            raise LibraryBackendError(f"Couldn't create Drive folder ({resp.status}): {text[:200]}")
        data = await resp.json()
        self.settings["folder_id"] = data["id"]

    async def _ensure_manifest(self) -> None:
        if self.settings.get("manifest_file_id"):
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
        await session.delete(f"{_GOOGLE_DRIVE_API}/files/{file_id}", headers=self._headers())

    async def _read_manifest(self) -> dict[str, Any]:
        raw = await self._download_content(self.settings["manifest_file_id"])
        if raw is None:
            return {"images": []}
        return json.loads(raw.decode("utf-8"))

    async def _write_manifest(self, manifest: dict[str, Any]) -> None:
        await self._upload_content(
            self.settings["manifest_file_id"],
            json.dumps(manifest).encode("utf-8"),
            "application/json",
        )

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
        manifest = await self._read_manifest()
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
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        manifest = await self._read_manifest()
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            return None
        bin_file_id = entry.get("bin_file_ids", {}).get(f"{width}x{height}")
        if not bin_file_id:
            return None
        return await self._download_content(bin_file_id)

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        manifest = await self._read_manifest()
        entry = self._find_entry(manifest, image_id)
        res_key = f"{width}x{height}"
        existing_id = entry.get("bin_file_ids", {}).get(res_key)
        if existing_id:
            await self._upload_content(existing_id, data, "application/octet-stream")
            return
        file_id = await self._create_file(f"{image_id}_{res_key}.bin", data, "application/octet-stream")
        entry.setdefault("bin_file_ids", {})[res_key] = file_id
        if [width, height] not in entry.setdefault("resolutions", []):
            entry["resolutions"].append([width, height])
        await self._write_manifest(manifest)

    async def async_update_image_fields(self, image_id: str, **fields: Any) -> None:
        manifest = await self._read_manifest()
        entry = self._find_entry(manifest, image_id)
        entry.update(fields)
        await self._write_manifest(manifest)

    async def async_bulk_update_image_fields(
        self, updates: dict[str, dict[str, Any]]
    ) -> None:
        manifest = await self._read_manifest()
        for d in manifest.get("images", []):
            fields = updates.get(d["image_id"])
            if fields:
                d.update(fields)
        await self._write_manifest(manifest)

    async def async_delete_bin(self, image_id: str, width: int, height: int) -> None:
        manifest = await self._read_manifest()
        entry = self._find_entry(manifest, image_id)
        res_key = f"{width}x{height}"
        bin_file_id = entry.get("bin_file_ids", {}).pop(res_key, None)
        if bin_file_id:
            await self._delete_file(bin_file_id)
            await self._write_manifest(manifest)

    async def async_delete_image(self, image_id: str) -> None:
        manifest = await self._read_manifest()
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        if entry is None:
            return
        if entry.get("drive_file_id"):
            await self._delete_file(entry["drive_file_id"])
        for bin_file_id in entry.get("bin_file_ids", {}).values():
            await self._delete_file(bin_file_id)
        manifest["images"] = [
            d for d in manifest.get("images", []) if d["image_id"] != image_id
        ]
        await self._write_manifest(manifest)


# ---------------------------------------------------------------------------
# Manager -- backend-agnostic operations used by the HTTP views
# ---------------------------------------------------------------------------


class LibraryManager:
    """Owns the active backend and implements upload / send-from-library
    logic that's the same regardless of which backend is active."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _SETTINGS_STORAGE_VERSION, _SETTINGS_STORAGE_KEY)
        self._settings: dict[str, Any] = {"backend": BACKEND_LOCAL}
        self._backend: LibraryBackend = LocalLibraryBackend(hass)
        self._pending_google_oauth: dict[str, dict[str, Any]] = {}

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
        """Load persisted backend settings (if any) and stand up that backend."""
        stored = await self._store.async_load()
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
        return external_url.rstrip("/") + "/api/fraimic/library/oauth/google/callback"

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
        """Generate whatever .bin resolutions `record` is missing for the
        frames currently configured."""
        missing = [
            (w, h) for w, h in _all_frame_resolutions(self.hass)
            if not record.has_resolution(w, h)
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

        from .image_converter import convert_image_bytes  # noqa: PLC0415

        for width, height in missing:
            try:
                bin_bytes = await self.hass.async_add_executor_job(
                    convert_image_bytes, raw_bytes, width, height
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Failed converting library image %s to %dx%d: %s",
                    record.image_id, width, height, err,
                )
                continue
            await self._backend.async_save_bin(record.image_id, width, height, bin_bytes)

    async def _find_image(self, image_id: str) -> LibraryImage | None:
        images = await self._backend.async_list_images()
        return next((img for img in images if img.image_id == image_id), None)

    async def async_get_bin_for_send(
        self, image_id: str, width: int, height: int
    ) -> bytes:
        """Return a cached .bin, generating + caching it on the fly if this
        resolution hasn't been seen for this image before (e.g. a frame
        added after the image was uploaded, or a crop was just changed and
        invalidated the old cache). Uses the image's saved manual crop for
        this resolution if one exists; otherwise falls back to the
        automatic letterbox render."""
        cached = await self._backend.async_get_bin(image_id, width, height)
        if cached is not None:
            return cached

        raw_bytes, _content_type = await self._backend.async_get_original(image_id)
        record = await self._find_image(image_id)
        crop_box = (record.crops if record else {}).get(f"{width}x{height}")

        if crop_box:
            from .image_converter import convert_image_bytes_cropped  # noqa: PLC0415

            bin_bytes = await self.hass.async_add_executor_job(
                convert_image_bytes_cropped, raw_bytes, width, height, tuple(crop_box)
            )
        else:
            from .image_converter import convert_image_bytes  # noqa: PLC0415

            bin_bytes = await self.hass.async_add_executor_job(
                convert_image_bytes, raw_bytes, width, height
            )
        await self._backend.async_save_bin(image_id, width, height, bin_bytes)
        return bin_bytes

    async def async_set_crop(
        self, image_id: str, width: int, height: int, crop_box: list[float]
    ) -> dict[str, Any]:
        """Persist a manual crop rectangle for one image at one resolution,
        and drop any cached .bin for that resolution so the next send picks
        up the new crop instead of a stale render."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        crops = dict(record.crops)
        crops[f"{width}x{height}"] = [float(v) for v in crop_box]
        await self._backend.async_update_image_fields(image_id, crops=crops)
        await self._backend.async_delete_bin(image_id, width, height)
        record.crops = crops
        return record.to_dict()

    async def async_clear_crop(
        self, image_id: str, width: int, height: int
    ) -> dict[str, Any]:
        """Revert to the original (un-cropped, auto-letterboxed) rendering
        for one image at one resolution."""
        record = await self._find_image(image_id)
        if record is None:
            raise LibraryBackendError(f"Image '{image_id}' not found")
        crops = dict(record.crops)
        crops.pop(f"{width}x{height}", None)
        await self._backend.async_update_image_fields(image_id, crops=crops)
        await self._backend.async_delete_bin(image_id, width, height)
        record.crops = crops
        return record.to_dict()

    async def async_delete(self, image_id: str) -> None:
        await self._backend.async_delete_image(image_id)

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
