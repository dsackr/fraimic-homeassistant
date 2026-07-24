"""Scene packs: curated art bundle install/sync/uninstall (KPF 17).

If this silently breaks: an interrupted install leaves orphaned images
untracked (never cleaned up, blocks reinstall); uninstall can leave stray
images if some deletes fail.

Widget packs (KPF 18: agenda/quotes/scripture add-ons with subprocess
scheduling) aren't covered here -- see TESTING_STRATEGY.md's tracker.
"""

from __future__ import annotations

import uuid

import pytest

from custom_components.digital_frames.scene_packs import (
    ScenePackError,
    ScenePackManager,
    _assign_images_to_frames,
)


# ---------------------------------------------------------------------------
# _assign_images_to_frames: pure orientation-aware round robin
# ---------------------------------------------------------------------------


def test_assign_prefers_matching_orientation():
    frames = [("landscape-frame", True), ("portrait-frame", False)]
    images = [("img-portrait", False), ("img-landscape", True)]
    mappings = _assign_images_to_frames(frames, images)
    assert mappings["landscape-frame"] == "img-landscape"
    assert mappings["portrait-frame"] == "img-portrait"


def test_assign_falls_back_to_all_pool_when_orientation_exhausted():
    frames = [("landscape-1", True), ("landscape-2", True)]
    images = [("img-portrait", False)]
    mappings = _assign_images_to_frames(frames, images)
    # No landscape images at all -- both frames fall back to the "all" pool.
    assert mappings["landscape-1"] == "img-portrait"
    assert mappings["landscape-2"] == "img-portrait"


def test_assign_no_images_produces_no_mappings():
    assert _assign_images_to_frames([("frame-1", True)], []) == {}


def test_assign_cycles_through_pool_round_robin():
    frames = [("f1", False), ("f2", False), ("f3", False)]
    images = [("i1", False), ("i2", False)]
    mappings = _assign_images_to_frames(frames, images)
    assert mappings == {"f1": "i1", "f2": "i2", "f3": "i1"}


def test_version_tuple_and_pack_compat():
    from custom_components.digital_frames.scene_packs import (
        _pack_compatible,
        _version_tuple,
    )

    assert _version_tuple("0.12.125") == (0, 12, 125)
    assert _version_tuple("v1.0.0-beta") == (1, 0, 0)
    assert _version_tuple("") == (0,)
    assert _pack_compatible({"min_integration": "0.12.0"}, "0.12.125") is True
    assert _pack_compatible({"min_integration": "9.0.0"}, "0.12.125") is False
    assert _pack_compatible({}, "0.1.0") is True


async def test_install_rejects_checksum_mismatch(
    hass, scene_pack_manager, aioclient_mock, sample_image_bytes, make_frame_entry
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    images = [
        {
            "filename": "a.jpg",
            "path": "scene_packs/monet/a.jpg",
            "sha256": "0" * 64,
        }
    ]
    url, body = _catalog_url_and_body(images)
    body["schema_version"] = 1
    body["catalog_version"] = "1.0.0"
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    with pytest.raises(ScenePackError, match="Checksum mismatch"):
        await scene_pack_manager.async_install_pack("monet")


async def test_catalog_hides_incompatible_min_integration(
    hass, scene_pack_manager, aioclient_mock, monkeypatch
):
    from custom_components.digital_frames import scene_packs as sp
    from custom_components.digital_frames.const import SCENE_PACK_INDEX_URL

    monkeypatch.setattr(sp, "_integration_version", lambda: "0.12.0")
    aioclient_mock.get(
        SCENE_PACK_INDEX_URL,
        json={
            "schema_version": 1,
            "catalog_version": "1.0.0",
            "packs": [
                {"id": "old", "name": "Old", "min_integration": "0.1.0", "images": []},
                {
                    "id": "future",
                    "name": "Future",
                    "min_integration": "99.0.0",
                    "images": [],
                },
            ],
        },
    )
    packs = await scene_pack_manager.async_list_available()
    assert [p["id"] for p in packs] == ["old"]
    assert scene_pack_manager.catalog_meta().get("packs_hidden_incompatible") == 1


# ---------------------------------------------------------------------------
# Install / sync / uninstall (fake library + mocked catalog fetch)
# ---------------------------------------------------------------------------


class _FakeLibrary:
    def __init__(self):
        self._images: dict[str, dict] = {}

    async def async_upload(self, filename, raw_bytes, albums):
        image_id = uuid.uuid4().hex[:8]
        self._images[image_id] = {
            "image_id": image_id,
            "filename": filename,
            "albums": list(albums),
        }
        return dict(self._images[image_id])

    async def async_list_images(self):
        return list(self._images.values())

    async def async_delete(self, image_id):
        self._images.pop(image_id, None)

    async def async_set_image_albums(self, image_id, albums):
        if image_id in self._images:
            self._images[image_id]["albums"] = list(albums)

    async def async_set_image_voice_name(self, image_id, voice_name):
        if image_id in self._images:
            self._images[image_id]["voice_name"] = voice_name


@pytest.fixture
def fake_library():
    return _FakeLibrary()


@pytest.fixture
def scene_pack_manager(hass, fake_library):
    from custom_components.digital_frames.scenes import SceneManager

    scene_manager = SceneManager(hass)
    return ScenePackManager(hass, fake_library, scene_manager)


def _catalog_url_and_body(images):
    from custom_components.digital_frames.const import SCENE_PACK_INDEX_URL

    return SCENE_PACK_INDEX_URL, {
        "packs": [
            {
                "id": "monet",
                "name": "Monet",
                "images": images,
            }
        ]
    }


def _image_url(spec):
    from custom_components.digital_frames.const import SCENE_PACK_RAW_BASE

    return f"{SCENE_PACK_RAW_BASE}/{spec['path']}"


async def test_install_pack_success(
    hass, scene_pack_manager, aioclient_mock, sample_image_bytes, make_frame_entry
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    images = [
        {"filename": "a.jpg", "path": "scene_packs/monet/a.jpg", "title": "Impression, Sunrise"},
        {"filename": "b.jpg", "path": "scene_packs/monet/b.jpg"},
    ]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))
    aioclient_mock.get(_image_url(images[1]), content=sample_image_bytes(600, 800))

    result = await scene_pack_manager.async_install_pack("monet")

    assert result["success"] is True
    assert result["images_added"] == 2
    assert result["scene_created"] is True
    assert result["errors"] == []

    # Verify voice name was populated from the spec's title
    lib_images = await scene_pack_manager._library.async_list_images()
    assert len(lib_images) == 2
    img_a = next(img for img in lib_images if img["filename"] == "a.jpg")
    assert img_a.get("voice_name") == "Impression, Sunrise"
    img_b = next(img for img in lib_images if img["filename"] == "b.jpg")
    assert img_b.get("voice_name") is None


async def test_install_pack_library_only_skips_scene(
    hass, scene_pack_manager, aioclient_mock, sample_image_bytes, make_frame_entry
):
    """Content Platform Phase 2: create_scene=False still tracks the pack."""
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    images = [
        {"filename": "a.jpg", "path": "scene_packs/monet/a.jpg", "title": "Sunrise"},
    ]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    result = await scene_pack_manager.async_install_pack("monet", create_scene=False)

    assert result["success"] is True
    assert result["images_added"] == 1
    assert result["scene_created"] is False
    assert scene_pack_manager._installed["monet"]["scene_id"] is None
    assert len(await scene_pack_manager._library.async_list_images()) == 1
    assert len(scene_pack_manager._scenes.scenes) == 0


async def test_install_pack_per_image_failure_does_not_strand_others(
    hass, scene_pack_manager, aioclient_mock, sample_image_bytes
):
    images = [
        {"filename": "good.jpg", "path": "scene_packs/monet/good.jpg"},
        {"filename": "bad.jpg", "path": "scene_packs/monet/bad.jpg"},
    ]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))
    aioclient_mock.get(_image_url(images[1]), status=404)

    result = await scene_pack_manager.async_install_pack("monet")

    assert result["images_added"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["filename"] == "bad.jpg"


async def test_install_pack_all_images_fail_raises(
    hass, scene_pack_manager, aioclient_mock
):
    images = [{"filename": "bad.jpg", "path": "scene_packs/monet/bad.jpg"}]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), status=404)

    with pytest.raises(ScenePackError, match="Couldn't import any images"):
        await scene_pack_manager.async_install_pack("monet")


async def test_install_pack_already_installed_rejected(
    hass, scene_pack_manager, aioclient_mock, sample_image_bytes
):
    images = [{"filename": "a.jpg", "path": "scene_packs/monet/a.jpg"}]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    await scene_pack_manager.async_install_pack("monet")

    with pytest.raises(ScenePackError, match="already installed"):
        await scene_pack_manager.async_install_pack("monet")


async def test_catalog_fetch_http_error_raises(hass, scene_pack_manager, aioclient_mock):
    from custom_components.digital_frames.const import SCENE_PACK_INDEX_URL

    aioclient_mock.get(SCENE_PACK_INDEX_URL, status=500)

    with pytest.raises(ScenePackError, match="HTTP 500"):
        await scene_pack_manager.async_install_pack("monet")


async def test_uninstall_removes_scene_and_images(
    hass, scene_pack_manager, fake_library, aioclient_mock, sample_image_bytes, make_frame_entry
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    images = [{"filename": "a.jpg", "path": "scene_packs/monet/a.jpg"}]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    installed = await scene_pack_manager.async_install_pack("monet")
    assert installed["scene_created"] is True

    await scene_pack_manager.async_uninstall_pack("monet")

    assert await fake_library.async_list_images() == []
    with pytest.raises(ScenePackError, match="not installed"):
        await scene_pack_manager.async_uninstall_pack("monet")


async def test_uninstall_succeeds_when_remote_catalog_is_unreachable(
    hass, scene_pack_manager, fake_library, aioclient_mock, sample_image_bytes
):
    """Regression: uninstall used to fetch the pack from the remote catalog
    (async_get_pack) AFTER already deleting the scene, purely to read
    installed.get("album", pack["name"]) -- installed["album"] is always
    recorded at install time, so that fetch was both unnecessary and, if the
    catalog was unreachable or no longer listed this pack_id, left the scene
    gone and the pack stuck "installed" forever with every retry failing
    identically. Uninstall must not depend on the network at all."""
    images = [{"filename": "a.jpg", "path": "scene_packs/monet/a.jpg"}]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    await scene_pack_manager.async_install_pack("monet")

    # The catalog is now unreachable -- uninstall must still succeed.
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, status=500)

    await scene_pack_manager.async_uninstall_pack("monet")

    assert await fake_library.async_list_images() == []
    with pytest.raises(ScenePackError, match="not installed"):
        await scene_pack_manager.async_uninstall_pack("monet")


async def test_uninstall_untags_image_shared_with_another_album_instead_of_deleting(
    hass, scene_pack_manager, fake_library, aioclient_mock, sample_image_bytes
):
    images = [{"filename": "a.jpg", "path": "scene_packs/monet/a.jpg"}]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    await scene_pack_manager.async_install_pack("monet")
    [image] = await fake_library.async_list_images()
    # User manually added this image to another album before uninstalling.
    await fake_library.async_set_image_albums(image["image_id"], ["Monet", "My Favorites"])

    await scene_pack_manager.async_uninstall_pack("monet")

    remaining = await fake_library.async_list_images()
    assert len(remaining) == 1
    assert remaining[0]["albums"] == ["My Favorites"]


async def test_sync_recovers_missing_image_by_filename(
    hass, scene_pack_manager, fake_library, aioclient_mock, sample_image_bytes
):
    images = [
        {"filename": "a.jpg", "path": "scene_packs/monet/a.jpg"},
        {"filename": "b.jpg", "path": "scene_packs/monet/b.jpg"},
    ]
    url, body = _catalog_url_and_body(images)
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))
    aioclient_mock.get(_image_url(images[1]), content=sample_image_bytes(600, 800))

    await scene_pack_manager.async_install_pack("monet")

    # Simulate image "a.jpg" having been lost (e.g. deleted from the library
    # backend outside the integration).
    all_images = await fake_library.async_list_images()
    lost = next(img for img in all_images if img["filename"] == "a.jpg")
    await fake_library.async_delete(lost["image_id"])

    aioclient_mock.clear_requests()
    aioclient_mock.get(url, json=body)
    aioclient_mock.get(_image_url(images[0]), content=sample_image_bytes(800, 600))

    result = await scene_pack_manager.async_sync_pack("monet")

    assert result["images_added"] == 1
    assert result["already_ok"] == 1
    filenames = {img["filename"] for img in await fake_library.async_list_images()}
    assert filenames == {"a.jpg", "b.jpg"}


async def test_sync_not_installed_raises(hass, scene_pack_manager):
    with pytest.raises(ScenePackError, match="not installed"):
        await scene_pack_manager.async_sync_pack("monet")
