"""Cloud library backends (Dropbox / Google Drive): a failed remote delete
must not be silently treated as success (KPF 9).

If this silently breaks: a transient failure (expired token, rate limit,
5xx) orphans the file remotely while the manifest entry is removed anyway,
leaving no record the app could ever reference or retry against.
"""

from __future__ import annotations

import time

import pytest

from custom_components.digital_frames.library import (
    _DROPBOX_API,
    _GOOGLE_DRIVE_API,
    _GOOGLE_DRIVE_UPLOAD_API,
    DropboxLibraryBackend,
    GoogleDriveLibraryBackend,
    LibraryBackendError,
)


def _dropbox_backend(hass):
    backend = DropboxLibraryBackend(hass, {"access_token": "tok"})
    backend._manifest_cache.store(
        {
            "images": [
                {
                    "image_id": "img1",
                    "filename": "a.jpg",
                    "content_type": "image/jpeg",
                    "uploaded_at": 0,
                    "albums": [],
                }
            ]
        }
    )
    return backend


async def test_dropbox_delete_image_raises_on_failed_remote_delete(hass, aioclient_mock):
    backend = _dropbox_backend(hass)
    aioclient_mock.post(
        f"{_DROPBOX_API}/files/delete_v2",
        status=500,
        json={"error_summary": "internal_error"},
    )

    with pytest.raises(LibraryBackendError):
        await backend.async_delete_image("img1")

    # Never reached the manifest read-modify-write -- still tracked.
    manifest = backend._manifest_cache.get()
    assert manifest["images"][0]["image_id"] == "img1"


async def test_dropbox_delete_image_tolerates_already_deleted(hass, aioclient_mock):
    backend = _dropbox_backend(hass)
    aioclient_mock.post(
        f"{_DROPBOX_API}/files/delete_v2",
        status=409,
        json={"error_summary": "path_lookup/not_found/"},
    )
    aioclient_mock.post(
        f"{_DROPBOX_API}/files/list_folder",
        status=200,
        json={"entries": []},
    )
    aioclient_mock.post("https://content.dropboxapi.com/2/files/upload", status=200)

    # A 409 (already gone) must not raise -- the file's absence is the
    # desired end state.
    await backend.async_delete_image("img1")

    manifest = backend._manifest_cache.get()
    assert manifest["images"] == []


def _drive_backend(hass):
    backend = GoogleDriveLibraryBackend(
        hass,
        {
            "client_id": "c",
            "client_secret": "s",
            "refresh_token": "r",
            "manifest_file_id": "manifest123",
        },
    )
    backend._access_token = "tok"
    backend._access_token_expires = time.time() + 3600
    return backend


async def test_drive_delete_file_raises_on_failed_remote_delete(hass, aioclient_mock):
    backend = _drive_backend(hass)
    aioclient_mock.delete(
        f"{_GOOGLE_DRIVE_API}/files/file123",
        status=500,
        json={"error": "internal"},
    )

    with pytest.raises(LibraryBackendError):
        await backend._delete_file("file123")


async def test_drive_delete_file_tolerates_already_deleted(hass, aioclient_mock):
    backend = _drive_backend(hass)
    aioclient_mock.delete(f"{_GOOGLE_DRIVE_API}/files/file123", status=404)

    # A 404 (already gone) must not raise.
    await backend._delete_file("file123")


async def test_drive_delete_image_raises_and_does_not_touch_manifest_on_failed_delete(
    hass, aioclient_mock
):
    backend = _drive_backend(hass)
    backend._manifest_cache.store(
        {
            "images": [
                {
                    "image_id": "img1",
                    "filename": "a.jpg",
                    "content_type": "image/jpeg",
                    "uploaded_at": 0,
                    "albums": [],
                    "drive_file_id": "file123",
                    "bin_file_ids": {},
                }
            ]
        }
    )
    aioclient_mock.delete(f"{_GOOGLE_DRIVE_API}/files/file123", status=500, json={"error": "boom"})

    with pytest.raises(LibraryBackendError):
        await backend.async_delete_image("img1")

    manifest = backend._manifest_cache.get()
    assert manifest["images"][0]["image_id"] == "img1"


async def test_drive_delete_image_persists_partial_progress_on_bin_delete_failure(
    hass, aioclient_mock
):
    """KPF: a partway-through failure must not lose the deletes that already
    succeeded (issue #16) -- the persisted manifest should reflect exactly
    what's actually gone from Drive, not the pre-delete state.
    """
    backend = _drive_backend(hass)
    backend._manifest_cache.store(
        {
            "images": [
                {
                    "image_id": "img1",
                    "filename": "a.jpg",
                    "content_type": "image/jpeg",
                    "uploaded_at": 0,
                    "albums": [],
                    "drive_file_id": "file123",
                    "bin_file_ids": {"100x100": "bin1", "100x100_r90": "bin2"},
                }
            ]
        }
    )
    aioclient_mock.delete(f"{_GOOGLE_DRIVE_API}/files/file123", status=200)
    aioclient_mock.delete(f"{_GOOGLE_DRIVE_API}/files/bin1", status=200)
    aioclient_mock.delete(
        f"{_GOOGLE_DRIVE_API}/files/bin2", status=500, json={"error": "boom"}
    )
    aioclient_mock.patch(
        f"{_GOOGLE_DRIVE_UPLOAD_API}/files/manifest123?uploadType=media",
        status=200,
    )

    with pytest.raises(LibraryBackendError):
        await backend.async_delete_image("img1")

    manifest = backend._manifest_cache.get()
    entry = manifest["images"][0]
    # Primary file and the first bin variant were actually deleted on Drive
    # and that must be persisted, even though the whole call raised.
    assert entry["drive_file_id"] is None
    assert "100x100" not in entry["bin_file_ids"]
    # The variant whose delete failed is still tracked so it can be retried.
    assert entry["bin_file_ids"]["100x100_r90"] == "bin2"


async def test_drive_delete_bin_persists_partial_progress_on_delete_failure(
    hass, aioclient_mock
):
    """Same non-atomic-manifest hazard as async_delete_image, but for the
    dedicated bin-only delete path (issue #4).
    """
    backend = _drive_backend(hass)
    backend._manifest_cache.store(
        {
            "images": [
                {
                    "image_id": "img1",
                    "filename": "a.jpg",
                    "content_type": "image/jpeg",
                    "uploaded_at": 0,
                    "albums": [],
                    "bin_file_ids": {"100x100": "bin1", "100x100_r90": "bin2"},
                }
            ]
        }
    )
    aioclient_mock.delete(f"{_GOOGLE_DRIVE_API}/files/bin1", status=200)
    aioclient_mock.delete(
        f"{_GOOGLE_DRIVE_API}/files/bin2", status=500, json={"error": "boom"}
    )
    aioclient_mock.patch(
        f"{_GOOGLE_DRIVE_UPLOAD_API}/files/manifest123?uploadType=media",
        status=200,
    )

    with pytest.raises(LibraryBackendError):
        await backend.async_delete_bin("img1", 100, 100)

    manifest = backend._manifest_cache.get()
    entry = manifest["images"][0]
    assert "100x100" not in entry["bin_file_ids"]
    assert entry["bin_file_ids"]["100x100_r90"] == "bin2"
