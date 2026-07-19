"""HA services: send_image, send_scene, restart, sleep, refresh (KPF 5).

If this silently breaks: automations calling fraimic.send_image/send_scene
fail or send the wrong image; a path-traversal bug in media resolution
could leak files.
"""

from __future__ import annotations

import os

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from custom_components.digital_frames.const import API_REFRESH, API_RESTART, API_SLEEP, DOMAIN
from custom_components.digital_frames import _safe_media_join


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


async def _setup_frame(hass, make_frame_entry, **kwargs):
    entry = make_frame_entry(**kwargs)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _device_id_for_entry(hass, entry) -> str:
    dev_reg = dr.async_get(hass)
    for device in dev_reg.devices.values():
        if entry.entry_id in device.config_entries:
            return device.id
    raise AssertionError("no device registered for entry")


# ---------------------------------------------------------------------------
# _safe_media_join: path-escape rejection
# ---------------------------------------------------------------------------


def test_safe_media_join_normal_path():
    result = _safe_media_join("/media/local", "photo.jpg")
    assert result == os.path.normpath("/media/local/photo.jpg")


def test_safe_media_join_rejects_parent_escape():
    with pytest.raises(HomeAssistantError, match="Invalid media path"):
        _safe_media_join("/media/local", "../../etc/passwd")


def test_safe_media_join_rejects_absolute_override():
    with pytest.raises(HomeAssistantError, match="Invalid media path"):
        _safe_media_join("/media/local", "/etc/passwd")


# ---------------------------------------------------------------------------
# restart / sleep / refresh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service,endpoint",
    [("restart", API_RESTART), ("sleep", API_SLEEP), ("refresh", API_REFRESH)],
)
async def test_command_services_call_correct_endpoint(
    hass, make_frame_entry, monkeypatch, service, endpoint
):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    calls = []
    orig = coordinator.async_send_command

    async def _spy(ep):
        calls.append(ep)
        return await orig(ep)

    monkeypatch.setattr(coordinator, "async_send_command", _spy)

    await hass.services.async_call(
        DOMAIN, service, {"device_id": device_id}, blocking=True
    )

    assert calls == [endpoint]


async def test_command_service_unknown_device_raises(hass, make_frame_entry):
    await _setup_frame(hass, make_frame_entry)

    with pytest.raises(HomeAssistantError, match="not found in device registry"):
        await hass.services.async_call(
            DOMAIN, "restart", {"device_id": "nonexistent"}, blocking=True
        )


# ---------------------------------------------------------------------------
# send_image
# ---------------------------------------------------------------------------


async def test_send_image_unknown_device_raises(hass, make_frame_entry):
    await _setup_frame(hass, make_frame_entry)

    with pytest.raises(HomeAssistantError, match="not found in device registry"):
        await hass.services.async_call(
            DOMAIN,
            "send_image",
            {"device_id": "nonexistent", "media_content_id": "/media/local/x.jpg"},
            blocking=True,
        )


async def test_send_image_missing_file_raises(hass, make_frame_entry, tmp_path):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)

    missing = str(tmp_path / "does_not_exist.jpg")
    with pytest.raises(HomeAssistantError, match="Media file not found"):
        await hass.services.async_call(
            DOMAIN,
            "send_image",
            {"device_id": device_id, "media_content_id": missing},
            blocking=True,
        )


async def test_send_image_success_converts_and_sends(
    hass, make_frame_entry, monkeypatch, tmp_path, sample_image_bytes
):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    img_path = tmp_path / "photo.jpg"
    img_path.write_bytes(sample_image_bytes(200, 200))

    sent = []

    async def _fake_send(image_bytes, *, image_id=None, thumbnail=None):
        sent.append(image_bytes)
        return {"success": True, "queued": False}

    monkeypatch.setattr(coordinator, "async_send_image_or_queue", _fake_send)

    await hass.services.async_call(
        DOMAIN,
        "send_image",
        {"device_id": device_id, "media_content_id": str(img_path)},
        blocking=True,
    )

    assert len(sent) == 1
    assert isinstance(sent[0], bytes)
    assert len(sent[0]) > 0


# ---------------------------------------------------------------------------
# send_scene
# ---------------------------------------------------------------------------


async def test_send_scene_not_found_raises(hass, make_frame_entry):
    await _setup_frame(hass, make_frame_entry)

    with pytest.raises(HomeAssistantError, match="not found"):
        await hass.services.async_call(
            DOMAIN, "send_scene", {"name": "Nonexistent Scene"}, blocking=True
        )


async def test_send_scene_all_mappings_fail_raises(hass, make_frame_entry, monkeypatch):
    await _setup_frame(hass, make_frame_entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]
    await scene_manager.async_save_scene("Broken Scene", {"gone-entry": "img1"})

    monkeypatch.setattr(
        scene_manager,
        "async_send_scene",
        _canned_result(
            [{"entry_id": "gone-entry", "success": False, "message": "Frame is no longer configured"}]
        ),
    )

    with pytest.raises(HomeAssistantError, match="failed to send to any frame"):
        await hass.services.async_call(
            DOMAIN, "send_scene", {"name": "Broken Scene"}, blocking=True
        )


async def test_send_scene_partial_failure_does_not_raise(
    hass, make_frame_entry, monkeypatch
):
    entry = await _setup_frame(hass, make_frame_entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]
    await scene_manager.async_save_scene(
        "Mixed Scene", {entry.entry_id: "img1", "gone-entry": "img2"}
    )

    monkeypatch.setattr(
        scene_manager,
        "async_send_scene",
        _canned_result(
            [
                {"entry_id": entry.entry_id, "success": True, "queued": False},
                {"entry_id": "gone-entry", "success": False, "message": "Frame is no longer configured"},
            ]
        ),
    )

    # Must not raise -- partial failure is logged, not surfaced as an error.
    await hass.services.async_call(
        DOMAIN, "send_scene", {"name": "Mixed Scene"}, blocking=True
    )


async def test_send_scene_all_queued_does_not_raise(hass, make_frame_entry, monkeypatch):
    entry = await _setup_frame(hass, make_frame_entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]
    await scene_manager.async_save_scene("Sleepy Scene", {entry.entry_id: "img1"})

    monkeypatch.setattr(
        scene_manager,
        "async_send_scene",
        _canned_result(
            [{"entry_id": entry.entry_id, "success": False, "queued": True}]
        ),
    )

    # A queued mapping isn't a failure -- must not raise.
    await hass.services.async_call(
        DOMAIN, "send_scene", {"name": "Sleepy Scene"}, blocking=True
    )


def _canned_result(results):
    async def _fake(hass, scene_id):
        return {"results": results}

    return _fake


def _canned_mappings_result(results):
    async def _fake(hass, mappings):
        return {"results": results}

    return _fake


# ---------------------------------------------------------------------------
# send_skill
# ---------------------------------------------------------------------------


async def test_send_skill_success_routes_through_send_mappings(
    hass, make_frame_entry, monkeypatch
):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]

    calls = []

    async def _fake_send_mappings(hass_arg, mappings):
        calls.append(mappings)
        return {"results": [{"entry_id": entry.entry_id, "success": True}]}

    monkeypatch.setattr(scene_manager, "async_send_mappings", _fake_send_mappings)

    await hass.services.async_call(
        DOMAIN,
        "send_skill",
        {"device_id": device_id, "skill_id": "word_of_the_day"},
        blocking=True,
    )

    assert calls == [{entry.entry_id: {"type": "skill", "skill_id": "word_of_the_day"}}]


async def test_send_skill_failure_raises(hass, make_frame_entry, monkeypatch):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]

    monkeypatch.setattr(
        scene_manager,
        "async_send_mappings",
        _canned_mappings_result(
            [{"entry_id": entry.entry_id, "success": False, "message": "Rendering failed: boom"}]
        ),
    )

    with pytest.raises(HomeAssistantError, match="Rendering failed: boom"):
        await hass.services.async_call(
            DOMAIN,
            "send_skill",
            {"device_id": device_id, "skill_id": "word_of_the_day"},
            blocking=True,
        )


async def test_send_skill_queued_does_not_raise(hass, make_frame_entry, monkeypatch):
    entry = await _setup_frame(hass, make_frame_entry)
    device_id = _device_id_for_entry(hass, entry)
    scene_manager = hass.data[DOMAIN]["_scenes"]

    monkeypatch.setattr(
        scene_manager,
        "async_send_mappings",
        _canned_mappings_result([{"entry_id": entry.entry_id, "success": False, "queued": True}]),
    )

    # A queued mapping isn't a failure -- must not raise.
    await hass.services.async_call(
        DOMAIN,
        "send_skill",
        {"device_id": device_id, "skill_id": "word_of_the_day"},
        blocking=True,
    )


async def test_send_skill_unknown_device_raises(hass, make_frame_entry):
    await _setup_frame(hass, make_frame_entry)

    with pytest.raises(HomeAssistantError, match="not found in device registry"):
        await hass.services.async_call(
            DOMAIN,
            "send_skill",
            {"device_id": "does-not-exist", "skill_id": "word_of_the_day"},
            blocking=True,
        )
