"""Manual crop editing (KPF 12), album management (KPF 13), and the
`.bin` cache + background backfill (KPF 11).

If crop silently breaks: a saved crop doesn't apply on next send, or
clearing a crop leaves stale cached renders for the same orientation.
If albums silently break: rename/delete misses images, or the default
"Images" album gets renamed/deleted.
If backfill silently breaks: sends are slow, or a send uses stale bytes
after a crop change if cache invalidation is missed.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.helpers import RenderSpec
from custom_components.digital_frames.library import DEFAULT_ALBUM, LibraryBackendError, LibraryManager


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    return manager


# ---------------------------------------------------------------------------
# Manual crop
# ---------------------------------------------------------------------------


async def test_save_crop_for_exact_resolution_invalidates_that_bin(
    library_manager, sample_image_bytes
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]
    await library_manager._backend.async_save_bin(image_id, 1200, 1600, b"stale-bin")

    await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.1, 0.9, 0.9])

    assert await library_manager._backend.async_get_bin(image_id, 1200, 1600) is None


async def test_save_crop_persists_and_is_readable_back(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]

    updated = await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.2, 0.8, 0.9])

    assert updated["crops"]["1200x1600"] == [0.1, 0.2, 0.8, 0.9]
    # Saving an exact-resolution crop also seeds the orientation fallback.
    assert updated["crops"]["portrait"] == [0.1, 0.2, 0.8, 0.9]


async def test_save_fallback_orientation_crop_invalidates_matching_resolutions(
    library_manager, sample_image_bytes
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]
    # 13.3" (1200x1600) and 31.5" (2560x1440, used sideways as 1440x2560)
    # are both portrait-oriented at these dimensions.
    await library_manager._backend.async_save_bin(image_id, 1200, 1600, b"stale-1")
    await library_manager._backend.async_save_bin(image_id, 1440, 2560, b"stale-2")

    await library_manager.async_set_crop(image_id, "portrait", 0, [0.0, 0.0, 1.0, 1.0])

    assert await library_manager._backend.async_get_bin(image_id, 1200, 1600) is None
    assert await library_manager._backend.async_get_bin(image_id, 1440, 2560) is None


async def test_clear_crop_reverts_and_invalidates(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]
    await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.1, 0.9, 0.9])
    await library_manager._backend.async_save_bin(image_id, 1200, 1600, b"freshly-cropped-bin")

    updated = await library_manager.async_clear_crop(image_id, 1200, 1600)

    assert "1200x1600" not in updated["crops"]
    assert await library_manager._backend.async_get_bin(image_id, 1200, 1600) is None


async def test_crop_on_unknown_image_raises(library_manager):
    with pytest.raises(LibraryBackendError, match="not found"):
        await library_manager.async_set_crop("nonexistent", 1200, 1600, [0, 0, 1, 1])


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------


async def test_new_album_created_via_tagging(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(100, 100))
    count = await library_manager.async_add_images_to_album([record["image_id"]], "Vacation")
    assert count == 1

    albums = await library_manager.async_list_albums()
    names = {a["name"] for a in albums}
    assert "Vacation" in names
    assert DEFAULT_ALBUM in names


async def test_rename_album_across_multiple_images(library_manager, sample_image_bytes):
    r1 = await library_manager.async_upload("a.jpg", sample_image_bytes(100, 100), ["Old Name"])
    r2 = await library_manager.async_upload("b.jpg", sample_image_bytes(100, 100), ["Old Name"])

    count = await library_manager.async_rename_album("Old Name", "New Name")
    assert count == 2

    images = await library_manager.async_list_images()
    for img in images:
        assert "Old Name" not in img["albums"]
        assert "New Name" in img["albums"]


async def test_delete_album_untags_without_deleting_photos(library_manager, sample_image_bytes):
    record = await library_manager.async_upload(
        "a.jpg", sample_image_bytes(100, 100), ["Temp Album"]
    )
    count = await library_manager.async_delete_album("Temp Album")
    assert count == 1

    images = await library_manager.async_list_images()
    assert len(images) == 1
    assert images[0]["image_id"] == record["image_id"]
    assert "Temp Album" not in images[0]["albums"]
    assert images[0]["albums"] == [DEFAULT_ALBUM]


async def test_rename_default_album_rejected(library_manager):
    with pytest.raises(LibraryBackendError, match="can't be renamed"):
        await library_manager.async_rename_album(DEFAULT_ALBUM, "Something Else")


async def test_delete_default_album_rejected(library_manager):
    with pytest.raises(LibraryBackendError, match="can't be deleted"):
        await library_manager.async_delete_album(DEFAULT_ALBUM)


async def test_rename_to_default_album_name_rejected(library_manager, sample_image_bytes):
    await library_manager.async_upload("a.jpg", sample_image_bytes(100, 100), ["Custom"])
    with pytest.raises(LibraryBackendError, match="use the album picker"):
        await library_manager.async_rename_album("Custom", DEFAULT_ALBUM)


async def test_add_to_album_with_empty_image_ids_rejected(library_manager):
    with pytest.raises(LibraryBackendError, match="at least one photo"):
        await library_manager.async_add_images_to_album([], "Some Album")


async def test_add_to_album_with_empty_name_rejected(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("a.jpg", sample_image_bytes(100, 100))
    with pytest.raises(LibraryBackendError, match="can't be empty"):
        await library_manager.async_add_images_to_album([record["image_id"]], "  ")


# ---------------------------------------------------------------------------
# .bin cache + background backfill
# ---------------------------------------------------------------------------


async def test_backfill_generates_bin_for_configured_frame_resolution(
    hass, library_manager, make_frame_entry, sample_image_bytes
):
    entry = make_frame_entry(width=1200, height=1600)
    entry.add_to_hass(hass)

    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    await hass.async_block_till_done()

    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SPLIT_HALF

    cached = await library_manager._backend.async_get_bin(
        record["image_id"], 1200, 1600, "", CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached is not None


async def test_get_bin_for_send_generates_on_the_fly_when_uncached(
    library_manager, sample_image_bytes
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)

    bin_bytes = await library_manager.async_get_bin_for_send(record["image_id"], spec)
    assert len(bin_bytes) == (1200 * 1600) // 2

    # Cached under the Phase-2 codec-keyed path (13.3" → spectra6_split_half).
    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SPLIT_HALF

    cached = await library_manager._backend.async_get_bin(
        record["image_id"], 1200, 1600, spec.variant, CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached == bin_bytes


async def test_get_bin_for_send_cache_hit_skips_conversion(
    library_manager, sample_image_bytes, monkeypatch
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)
    await library_manager.async_get_bin_for_send(record["image_id"], spec)

    from custom_components.digital_frames import image_converter

    calls = []
    monkeypatch.setattr(
        image_converter,
        "convert_image_bytes",
        lambda *a, **kw: calls.append(1) or b"should-not-be-used",
    )

    cached = await library_manager.async_get_bin_for_send(record["image_id"], spec)
    assert calls == []
    assert cached != b"should-not-be-used"


async def test_get_bin_for_send_pack_method_override_bypasses_cache(
    library_manager, sample_image_bytes
):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)
    normal = await library_manager.async_get_bin_for_send(record["image_id"], spec)

    legacy = await library_manager.async_get_bin_for_send(
        record["image_id"], spec, pack_method="legacy"
    )
    assert legacy == normal  # byte-identical per image_converter's own guarantee

    # The override must not have polluted the cache with anything different.
    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SPLIT_HALF

    cached = await library_manager._backend.async_get_bin(
        record["image_id"], 1200, 1600, spec.variant, CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached == normal


# ---------------------------------------------------------------------------
# FramePort Phase 2: codec_id in .bin cache keys
# ---------------------------------------------------------------------------


async def test_bin_cache_keys_by_codec_id(library_manager, sample_image_bytes):
    from custom_components.digital_frames.frame_types import (
        CODEC_SPECTRA6_SEQUENTIAL,
        CODEC_SPECTRA6_SPLIT_HALF,
    )

    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(400, 300))
    image_id = record["image_id"]
    await library_manager._backend.async_save_bin(
        image_id, 800, 480, b"seq-payload", "", CODEC_SPECTRA6_SEQUENTIAL
    )
    await library_manager._backend.async_save_bin(
        image_id, 1200, 1600, b"split-payload", "", CODEC_SPECTRA6_SPLIT_HALF
    )

    assert (
        await library_manager._backend.async_get_bin(
            image_id, 800, 480, "", CODEC_SPECTRA6_SEQUENTIAL
        )
        == b"seq-payload"
    )
    assert (
        await library_manager._backend.async_get_bin(
            image_id, 1200, 1600, "", CODEC_SPECTRA6_SPLIT_HALF
        )
        == b"split-payload"
    )
    # Wrong codec at that geometry is a miss (no silent cross-serve).
    assert (
        await library_manager._backend.async_get_bin(
            image_id, 800, 480, "", CODEC_SPECTRA6_SPLIT_HALF
        )
        is None
    )


async def test_bin_cache_falls_back_to_legacy_path_for_same_geometry(
    library_manager, sample_image_bytes
):
    """Pre-Phase-2 bins (no codec dir) still serve when codec is requested."""
    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SPLIT_HALF

    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(400, 300))
    image_id = record["image_id"]
    # Legacy write (codec_id empty).
    await library_manager._backend.async_save_bin(image_id, 1200, 1600, b"legacy-bin")

    cached = await library_manager._backend.async_get_bin(
        image_id, 1200, 1600, "", CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached == b"legacy-bin"


async def test_get_bin_for_send_writes_codec_keyed_path(
    library_manager, sample_image_bytes
):
    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SEQUENTIAL

    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(400, 300))
    # 7.3" geometry → sequential codec.
    spec = RenderSpec(width=800, height=480, rotation=0, locked=False)
    bin_bytes = await library_manager.async_get_bin_for_send(
        record["image_id"], spec, codec_id=CODEC_SPECTRA6_SEQUENTIAL
    )
    assert len(bin_bytes) == (800 * 480) // 2

    codec_path = await library_manager._backend.async_get_bin(
        record["image_id"], 800, 480, "", CODEC_SPECTRA6_SEQUENTIAL
    )
    assert codec_path == bin_bytes
    # Must not only live on the legacy path.
    # (Legacy empty get without codec still reads only the old layout.)
    # After Phase-2 writes, the primary location is the codec subdir.
