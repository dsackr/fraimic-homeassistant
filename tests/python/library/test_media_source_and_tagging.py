"""Tests for the media_source platform and AI auto-tagging capability."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.components.media_source import (
    BrowseMediaSource,
    PlayMedia,
    async_resolve_media,
    async_browse_media,
)
from homeassistant.components.media_player import MediaClass, MediaType

from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.media_source import FraimicMediaSource


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    class _FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            return {"battery": 90, "width": 1200, "height": 1600}

    class _FakeSession:
        def get(self, *a, **kw):
            return _FakeResponse()

        def post(self, *a, **kw):
            return _FakeResponse()

    monkeypatch.setattr(
        "custom_components.digital_frames.coordinator.async_get_clientsession",
        lambda hass: _FakeSession(),
    )


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    return manager


@pytest.fixture
def mock_ai_task(hass: HomeAssistant):
    """Set up a mock ai_task entity and service."""
    calls = []

    async def mock_generate_data(call: ServiceCall) -> ServiceResponse:
        calls.append(call)
        return {"data": "beach, sunset, landscape"}

    hass.services.async_register(
        "ai_task",
        "generate_data",
        mock_generate_data,
        supports_response=SupportsResponse.ONLY,
    )

    hass.states.async_set(
        "ai_task.mock_ai",
        "active",
        {"supported_features": 3},  # 1 (GENERATE_DATA) | 2 (SUPPORT_ATTACHMENTS)
    )

    return calls


async def test_auto_tagging_enabled(
    hass, library_manager, sample_image_bytes, mock_ai_task
):
    # Setup library setting with auto-tagging enabled
    await library_manager.async_set_ai_auto_tagging(True)
    hass.data.setdefault(DOMAIN, {})["_library"] = library_manager

    # Upload image
    record = await library_manager.async_upload(
        "photo.jpg", sample_image_bytes(200, 200)
    )
    
    # Wait for the background auto-tagging task to complete
    await hass.async_block_till_done()

    # Verify that the service was called
    assert len(mock_ai_task) == 1
    call = mock_ai_task[0]
    assert call.data["entity_id"] == "ai_task.mock_ai"
    assert call.data["attachments"][0]["media_content_id"] == f"media-source://{DOMAIN}/image/{record['image_id']}"

    # Verify tags updated in manifest
    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert sorted(images[0]["tags"]) == ["beach", "landscape", "sunset"]


async def test_auto_tagging_disabled(
    hass, library_manager, sample_image_bytes, mock_ai_task
):
    # Setup library setting with auto-tagging disabled
    await library_manager.async_set_ai_auto_tagging(False)
    hass.data.setdefault(DOMAIN, {})["_library"] = library_manager

    # Upload image
    record = await library_manager.async_upload(
        "photo.jpg", sample_image_bytes(200, 200)
    )
    
    # Wait for any potential background tasks
    await hass.async_block_till_done()

    # Verify that the service was not called
    assert len(mock_ai_task) == 0

    # Verify tags are empty
    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert images[0]["tags"] == []


async def test_media_source_resolve_and_browse(
    hass, library_manager, sample_image_bytes
):
    hass.data.setdefault(DOMAIN, {})["_library"] = library_manager

    # Upload an image to test with
    record = await library_manager.async_upload(
        "photo.jpg", sample_image_bytes(200, 200)
    )

    media_source = FraimicMediaSource(hass)

    # 1. Resolve media item
    from homeassistant.components.media_source import MediaSourceItem
    item = MediaSourceItem(hass, DOMAIN, f"image/{record['image_id']}", None)
    playable = await media_source.async_resolve_media(item)
    assert isinstance(playable, PlayMedia)
    assert playable.url == f"/api/digital_frames/library/image/{record['image_id']}"
    assert playable.mime_type == "image/png"
    assert playable.path is not None
    assert str(playable.path).endswith(record["filename"])

    # 2. Browse Root
    root_item = MediaSourceItem(hass, DOMAIN, "", None)
    root_browse = await media_source.async_browse_media(root_item)
    assert isinstance(root_browse, BrowseMediaSource)
    assert root_browse.identifier == ""
    assert root_browse.media_class == MediaClass.DIRECTORY
    # Expect "All Images" plus the default "Images" album folder
    assert len(root_browse.children) == 2
    assert root_browse.children[0].identifier == "all"
    assert root_browse.children[1].identifier == "album/Images"

    # 3. Browse "all" folder
    all_item = MediaSourceItem(hass, DOMAIN, "all", None)
    all_browse = await media_source.async_browse_media(all_item)
    assert isinstance(all_browse, BrowseMediaSource)
    assert len(all_browse.children) == 1
    assert all_browse.children[0].identifier == f"image/{record['image_id']}"
    assert all_browse.children[0].can_play is True
    assert all_browse.children[0].can_expand is False

    # 4. Browse specific album folder
    album_item = MediaSourceItem(hass, DOMAIN, "album/Images", None)
    album_browse = await media_source.async_browse_media(album_item)
    assert isinstance(album_browse, BrowseMediaSource)
    assert len(album_browse.children) == 1
    assert album_browse.children[0].identifier == f"image/{record['image_id']}"


async def test_auto_tag_all_service(
    hass, make_frame_entry, sample_image_bytes, mock_ai_task
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    library_manager = hass.data[DOMAIN]["_library"]

    # 1. Upload one image that has tags and one that doesn't
    await library_manager.async_set_ai_auto_tagging(False)
    img1 = await library_manager.async_upload("photo1.jpg", sample_image_bytes(200, 200))
    img2 = await library_manager.async_upload("photo2.jpg", sample_image_bytes(200, 200))

    # Manually assign tags to img1
    await library_manager._backend.async_update_image_fields(
        img1["image_id"], tags=["already_tagged"]
    )

    # 2. Call auto_tag_all service without overwrite
    await hass.services.async_call(
        DOMAIN,
        "auto_tag_all",
        {"overwrite": False},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Verify mock AI task was called only for the untagged image (img2)
    assert len(mock_ai_task) == 1
    assert mock_ai_task[0].data["attachments"][0]["media_content_id"] == f"media-source://{DOMAIN}/image/{img2['image_id']}"

    # Verify tags updated in manifest for img2, and unchanged for img1
    images_after = await library_manager.async_list_images()
    tags_by_id = {img["image_id"]: img.get("tags", []) for img in images_after}
    assert tags_by_id[img1["image_id"]] == ["already_tagged"]
    assert sorted(tags_by_id[img2["image_id"]]) == ["beach", "landscape", "sunset"]

    # Reset mock AI task calls
    mock_ai_task.clear()

    # 3. Call auto_tag_all service with overwrite=True
    await hass.services.async_call(
        DOMAIN,
        "auto_tag_all",
        {"overwrite": True},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Verify mock AI task was called for both images
    assert len(mock_ai_task) == 2
