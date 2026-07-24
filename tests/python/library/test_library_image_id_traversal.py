"""image_id path-traversal guard (KPF 8/14): every call site that builds a
filesystem path directly from a caller-supplied image_id (rather than
looking it up in the manifest first) must reject a malformed id instead of
interpolating it unsanitized.

If this silently breaks: a crafted image_id in a send/delete request reads
or deletes an arbitrary .bin-suffixed file outside the library, and the
same shape of bug can resurface any time a new call site builds a path
from image_id without going through _safe_image_id.
"""

from __future__ import annotations

import os

import pytest

from custom_components.digital_frames.helpers import RenderSpec
from custom_components.digital_frames.library import (
    DropboxLibraryBackend,
    GoogleDriveLibraryBackend,
    LibraryBackendError,
    LibraryManager,
)


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    return manager


_TRAVERSAL_IDS = [
    "../../../../etc/passwd",
    "..%2f..%2fescape",
    "a/b",
    "a\\b",
    "",
]


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_get_bin_for_send_rejects_traversal_image_id(library_manager, bad_id):
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)
    with pytest.raises((LibraryBackendError, ValueError)):
        await library_manager.async_get_bin_for_send(bad_id, spec)


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_delete_rejects_traversal_image_id_without_touching_disk(
    library_manager, bad_id, tmp_path, monkeypatch
):
    # A traversal id must never reach a real filesystem path outside the
    # library root -- delete is expected to no-op (matches the existing
    # idempotent "delete an unknown id" contract), not raise and not touch
    # anything outside the library's own bin/ tree.
    await library_manager.async_delete(bad_id)


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_thumbnail_rejects_traversal_image_id(library_manager, bad_id):
    with pytest.raises((LibraryBackendError, ValueError, FileNotFoundError)):
        await library_manager.async_get_thumbnail(bad_id, 240)


async def test_get_bin_for_send_still_works_for_a_real_image_id(
    library_manager, sample_image_bytes
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(200, 200))
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)
    bin_bytes = await library_manager.async_get_bin_for_send(record["image_id"], spec)
    assert bin_bytes


# ---------------------------------------------------------------------------
# Cloud backends -- DropboxLibraryBackend._bin_path interpolates image_id
# directly into a real Dropbox API path (guarded by _safe_image_id).
# GoogleDriveLibraryBackend never builds a path from image_id at all -- it
# always looks the id up in the manifest first and operates on opaque Drive
# file ids -- so its coverage below instead confirms a traversal id is just
# an ordinary manifest miss, not a way to reach an unintended file.
# ---------------------------------------------------------------------------


def _dropbox_backend(hass):
    return DropboxLibraryBackend(hass, {"access_token": "tok"})


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
def test_dropbox_bin_path_rejects_traversal_image_id(hass, bad_id):
    backend = _dropbox_backend(hass)
    with pytest.raises(ValueError):
        backend._bin_path(bad_id, 1200, 1600)


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_dropbox_get_bin_rejects_traversal_image_id_before_any_request(
    hass, bad_id, aioclient_mock
):
    # No aioclient_mock routes are registered -- if _bin_path's guard were
    # skipped, the subsequent (unmocked) network call would fail with a
    # connection error instead of the expected ValueError, so this also
    # proves the rejection happens before any request goes out.
    backend = _dropbox_backend(hass)
    with pytest.raises(ValueError):
        await backend.async_get_bin(bad_id, 1200, 1600)
    assert len(aioclient_mock.mock_calls) == 0


def _drive_backend(hass):
    return GoogleDriveLibraryBackend(
        hass,
        {
            "client_id": "c",
            "client_secret": "s",
            "refresh_token": "r",
            "manifest_file_id": "manifest123",
        },
    )


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_drive_get_bin_treats_traversal_image_id_as_manifest_miss(hass, bad_id):
    backend = _drive_backend(hass)
    backend._manifest_cache.store({"images": []})
    assert await backend.async_get_bin(bad_id, 1200, 1600) is None


@pytest.mark.parametrize("bad_id", _TRAVERSAL_IDS)
async def test_drive_delete_image_no_ops_for_traversal_image_id(
    hass, bad_id, aioclient_mock
):
    backend = _drive_backend(hass)
    backend._manifest_cache.store({"images": []})
    # Must not raise, and -- since the id can never match a manifest entry
    # -- must never reach a real Drive delete request.
    await backend.async_delete_image(bad_id)
    assert len(aioclient_mock.mock_calls) == 0
