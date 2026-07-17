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

from custom_components.fraimic.library import LibraryManager
from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.media_source import FraimicMediaSource


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
    assert playable.url == f"/api/fraimic/library/image/{record['image_id']}"
    assert playable.mime_type == "image/png"

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
