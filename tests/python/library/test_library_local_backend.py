"""Shared image library: upload, list, stream original, thumbnail (KPF 8),
against the local storage backend.

If this silently breaks: uploads silently fail per-file in a batch, or
thumbnails go stale/broken.
"""

from __future__ import annotations

import pytest

from custom_components.fraimic.library import LibraryManager


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    return manager


async def test_single_upload_is_listed(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(200, 200))
    assert record["filename"] == "photo.jpg"
    assert record["albums"] == ["Images"]

    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert images[0]["image_id"] == record["image_id"]


async def test_multiple_uploads_all_listed(library_manager, sample_image_bytes):
    for i in range(3):
        await library_manager.async_upload(f"photo{i}.jpg", sample_image_bytes(100, 100))

    images = await library_manager.async_list_images()
    assert len(images) == 3
    assert {img["filename"] for img in images} == {"photo0.jpg", "photo1.jpg", "photo2.jpg"}


async def test_upload_with_custom_albums(library_manager, sample_image_bytes):
    record = await library_manager.async_upload(
        "vacation.jpg", sample_image_bytes(100, 100), albums=["Vacation 2026"]
    )
    assert record["albums"] == ["Vacation 2026"]


async def test_upload_of_undecodable_bytes_is_not_rejected(library_manager):
    # The manager itself doesn't validate image content on upload (rejection,
    # if any, is an HTTP-layer concern) -- corrupt bytes still get stored
    # with a generic content type rather than raising.
    record = await library_manager.async_upload("broken.jpg", b"not-a-real-image")
    assert record["content_type"] == "application/octet-stream"


async def test_get_original_roundtrips_bytes(library_manager, sample_image_bytes):
    original_bytes = sample_image_bytes(150, 150)
    record = await library_manager.async_upload("photo.jpg", original_bytes)

    read_bytes, content_type = await library_manager.async_get_original(record["image_id"])
    assert read_bytes == original_bytes
    assert content_type == "image/png"


# ---------------------------------------------------------------------------
# Thumbnails: generated once, cached on local disk regardless of backend
# ---------------------------------------------------------------------------


async def test_thumbnail_generated_on_first_request_then_cached(
    library_manager, sample_image_bytes, monkeypatch
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(400, 400))

    calls = []
    from custom_components.fraimic import image_converter

    orig = image_converter.make_thumbnail

    def _spy(*args, **kwargs):
        calls.append(1)
        return orig(*args, **kwargs)

    monkeypatch.setattr(image_converter, "make_thumbnail", _spy)

    thumb1 = await library_manager.async_get_thumbnail(record["image_id"], 240)
    thumb2 = await library_manager.async_get_thumbnail(record["image_id"], 240)

    assert thumb1 == thumb2
    assert len(calls) == 1, "second request must hit the on-disk cache, not regenerate"


async def test_thumbnail_cache_is_per_edge_size(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(400, 400))
    small = await library_manager.async_get_thumbnail(record["image_id"], 120)
    large = await library_manager.async_get_thumbnail(record["image_id"], 480)
    assert small != large


async def test_delete_purges_original_and_thumbnails(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(200, 200))
    await library_manager.async_get_thumbnail(record["image_id"], 240)

    import os

    thumb_path = library_manager._thumb_path(record["image_id"], 240)
    assert os.path.isfile(thumb_path)

    await library_manager.async_delete(record["image_id"])

    assert await library_manager.async_list_images() == []
    assert not os.path.isfile(thumb_path)


async def test_delete_of_unknown_image_does_not_raise(library_manager):
    # async_delete_image on the local backend just no-ops for an id that
    # isn't in the manifest -- deleting twice (e.g. a double-click) must
    # not error.
    await library_manager.async_delete("never-existed")


async def test_update_voice_name(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(200, 200))
    assert record["voice_name"] is None

    updated = await library_manager.async_set_image_voice_name(record["image_id"], "my profile pic")
    assert updated["voice_name"] == "my profile pic"

    # Verify that listing the images returns the updated voice name
    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert images[0]["voice_name"] == "my profile pic"

    # Verify that loading from the manifest returns the updated voice name
    # (i.e. it was successfully written/serialized)
    new_manager = LibraryManager(library_manager.hass)
    await new_manager.async_load()
    images2 = await new_manager.async_list_images()
    assert len(images2) == 1
    assert images2[0]["voice_name"] == "my profile pic"

    # Verify clearing it works
    cleared = await library_manager.async_set_image_voice_name(record["image_id"], None)
    assert cleared["voice_name"] is None
    images3 = await library_manager.async_list_images()
    assert images3[0]["voice_name"] is None


async def test_update_tags(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(200, 200))
    assert record.get("tags") == []

    updated = await library_manager.async_set_image_tags(record["image_id"], ["Alyssa", "Kids"])
    assert updated["tags"] == ["Alyssa", "Kids"]

    # Verify that listing the images returns the updated tags
    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert images[0]["tags"] == ["Alyssa", "Kids"]

    # Verify that loading from the manifest returns the updated tags (persisted)
    new_manager = LibraryManager(library_manager.hass)
    await new_manager.async_load()
    images2 = await new_manager.async_list_images()
    assert len(images2) == 1
    assert images2[0]["tags"] == ["Alyssa", "Kids"]

    # Verify clearing/updating it works and cleans up formatting
    updated2 = await library_manager.async_set_image_tags(record["image_id"], [" Alyssa  ", "", "kids", "alyssa"])
    assert updated2["tags"] == ["Alyssa", "kids"]

