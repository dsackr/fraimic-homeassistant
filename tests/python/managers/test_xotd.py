"""xOTD: many independent (content_mode, frame, schedule) instances.

If this silently breaks: two instances of the same content mode collide
(one overwrites the other's schedule/config), or an Image mode instance
never actually reaches a frame because its in-process fetch/pick-and-send
path silently no-ops.

Text-mode (joke/quote/scripture/word) firing downloads and subprocess-execs
a script -- like scene_packs.py's widget execution, that's not covered
here (see test_scene_packs.py's module docstring for the same carve-out).
This file covers CRUD/validation and Image mode's fully in-process firing
(feed fetch + library tag + send, and album pick + send), which don't
touch a subprocess at all.
"""

from __future__ import annotations

import pytest

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.xotd import XotdError, XotdManager


class _FakeSceneManager:
    def __init__(self):
        self.sent = []

    async def async_send_mappings(self, hass, mappings):
        self.sent.append(dict(mappings))
        return {"results": [{"entry_id": k, "success": True} for k in mappings]}


class _FakeLibrary:
    def __init__(self, images=None):
        self.images = images or []
        self.uploads = []  # (filename, raw_bytes, albums)

    async def async_list_images(self):
        return list(self.images)

    async def async_upload(self, filename, raw_bytes, albums=None):
        record = {"image_id": f"uploaded_{len(self.uploads)}", "filename": filename, "albums": list(albums or [])}
        self.uploads.append(record)
        return record


@pytest.fixture
def fake_scene_manager(hass):
    mgr = _FakeSceneManager()
    hass.data.setdefault(DOMAIN, {})["_scenes"] = mgr
    return mgr


@pytest.fixture
def fake_library():
    return _FakeLibrary()


@pytest.fixture
def xotd_manager(hass, fake_library):
    return XotdManager(hass, fake_library, scene_packs=None)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_create_invalid_content_mode_rejected(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(XotdError, match="Invalid content_mode"):
        await xotd_manager.async_create_instance("carrier_pigeon", "e1", {"type": "hourly"}, {})


async def test_create_missing_frame_rejected(hass, xotd_manager):
    with pytest.raises(XotdError, match="target frame"):
        await xotd_manager.async_create_instance("joke", "does-not-exist", {"type": "hourly"}, {})


async def test_create_invalid_schedule_type_rejected(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(XotdError, match="Invalid schedule type"):
        await xotd_manager.async_create_instance("joke", "e1", {"type": "weekly"}, {})


async def test_create_daily_schedule_normalizes_time(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    created = await xotd_manager.async_create_instance(
        "joke", "e1", {"type": "daily", "time": "7:5"}, {}
    )
    assert created["schedule"] == {"type": "daily", "time": "07:05:00"}


async def test_create_image_mode_requires_sub_mode(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(XotdError, match="image sub_mode"):
        await xotd_manager.async_create_instance("image", "e1", {"type": "hourly"}, {})


async def test_create_image_feed_requires_known_provider(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(XotdError, match="feed_provider"):
        await xotd_manager.async_create_instance(
            "image", "e1", {"type": "hourly"}, {"sub_mode": "image_feed", "feed_provider": "carrier_pigeon"}
        )


async def test_create_image_album_requires_album_name(hass, xotd_manager, make_frame_entry):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(XotdError, match="needs an album"):
        await xotd_manager.async_create_instance("image", "e1", {"type": "hourly"}, {"sub_mode": "image_album"})


# ---------------------------------------------------------------------------
# Independent instance lifecycle
# ---------------------------------------------------------------------------


async def test_two_instances_stay_independent(hass, xotd_manager, make_frame_entry):
    entry_a = make_frame_entry(entry_id="e1")
    entry_a.add_to_hass(hass)
    entry_b = make_frame_entry(entry_id="e2")
    entry_b.add_to_hass(hass)

    joke = await xotd_manager.async_create_instance("joke", "e1", {"type": "hourly"}, {})
    scripture = await xotd_manager.async_create_instance(
        "scripture", "e2", {"type": "daily", "time": "08:00:00"}, {}
    )

    assert joke["instance_id"] != scripture["instance_id"]
    instances = await xotd_manager.async_list_instances()
    assert {i["instance_id"] for i in instances} == {joke["instance_id"], scripture["instance_id"]}

    updated = await xotd_manager.async_update_instance(
        joke["instance_id"], {"schedule": {"type": "daily", "time": "09:30:00"}}
    )
    assert updated["schedule"] == {"type": "daily", "time": "09:30:00"}

    untouched = await xotd_manager.async_get_instance(scripture["instance_id"])
    assert untouched["schedule"] == {"type": "daily", "time": "08:00:00"}
    assert untouched["frame_id"] == "e2"


async def test_delete_one_instance_leaves_the_other(hass, xotd_manager, make_frame_entry):
    entry_a = make_frame_entry(entry_id="e1")
    entry_a.add_to_hass(hass)
    entry_b = make_frame_entry(entry_id="e2")
    entry_b.add_to_hass(hass)

    joke = await xotd_manager.async_create_instance("joke", "e1", {"type": "hourly"}, {})
    scripture = await xotd_manager.async_create_instance("scripture", "e2", {"type": "hourly"}, {})

    await xotd_manager.async_delete_instance(joke["instance_id"])

    instances = await xotd_manager.async_list_instances()
    assert [i["instance_id"] for i in instances] == [scripture["instance_id"]]
    assert await xotd_manager.async_get_instance(joke["instance_id"]) is None


async def test_delete_unknown_instance_raises(hass, xotd_manager):
    with pytest.raises(XotdError, match="not found"):
        await xotd_manager.async_delete_instance("does-not-exist")


# ---------------------------------------------------------------------------
# Image mode: fully in-process firing (no subprocess)
# ---------------------------------------------------------------------------


async def test_image_album_fires_by_picking_from_the_named_album(
    hass, xotd_manager, fake_library, fake_scene_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.images = [
        {"image_id": "img1", "albums": ["Vacation"]},
        {"image_id": "img2", "albums": ["Family"]},
    ]

    instance = await xotd_manager.async_create_instance(
        "image", "e1", {"type": "hourly"}, {"sub_mode": "image_album", "album": "Vacation"}
    )
    record = await xotd_manager.async_get_instance(instance["instance_id"])
    from custom_components.fraimic.xotd import XotdInstance

    await xotd_manager._async_fire(XotdInstance(record))

    assert fake_scene_manager.sent == [{"e1": "img1"}]
    assert fake_library.uploads == []  # picking from an existing album never uploads anything


async def test_image_album_with_no_matching_images_does_not_send(
    hass, xotd_manager, fake_library, fake_scene_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.images = [{"image_id": "img1", "albums": ["Family"]}]

    instance = await xotd_manager.async_create_instance(
        "image", "e1", {"type": "hourly"}, {"sub_mode": "image_album", "album": "Vacation"}
    )
    from custom_components.fraimic.xotd import XotdInstance

    record = await xotd_manager.async_get_instance(instance["instance_id"])
    await xotd_manager._async_fire(XotdInstance(record))

    assert fake_scene_manager.sent == []


async def test_image_feed_uploads_tagged_to_image_of_the_day_and_sends(
    hass, xotd_manager, fake_library, fake_scene_manager, make_frame_entry, aioclient_mock
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    aioclient_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image", "url": "https://example.com/apod.jpg", "date": "2026-01-01"},
    )
    aioclient_mock.get("https://example.com/apod.jpg", content=b"fake-jpeg-bytes")

    instance = await xotd_manager.async_create_instance(
        "image", "e1", {"type": "hourly"}, {"sub_mode": "image_feed", "feed_provider": "nasa_apod"}
    )
    from custom_components.fraimic.xotd import XotdInstance

    record = await xotd_manager.async_get_instance(instance["instance_id"])
    await xotd_manager._async_fire(XotdInstance(record))

    assert len(fake_library.uploads) == 1
    assert fake_library.uploads[0]["albums"] == ["Image of the Day"]
    assert fake_scene_manager.sent == [{"e1": fake_library.uploads[0]["image_id"]}]


async def test_image_feed_skips_non_image_apod_without_uploading_or_sending(
    hass, xotd_manager, fake_library, fake_scene_manager, make_frame_entry, aioclient_mock
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    aioclient_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "video", "url": "https://example.com/apod.mp4", "date": "2026-01-01"},
    )

    instance = await xotd_manager.async_create_instance(
        "image", "e1", {"type": "hourly"}, {"sub_mode": "image_feed", "feed_provider": "nasa_apod"}
    )
    from custom_components.fraimic.xotd import XotdInstance

    record = await xotd_manager.async_get_instance(instance["instance_id"])
    await xotd_manager._async_fire(XotdInstance(record))

    assert fake_library.uploads == []
    assert fake_scene_manager.sent == []
