"""Voice/AI intent: "generate an image of X and send to [frame]" (KPF 6).

If this silently breaks: the voice command errors out or resolves to the
wrong frame.
"""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import intent as ha_intent

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.intent import (
    INTENT_GENERATE_AI_IMAGE,
    INTENT_SEND_SKILL,
    INTENT_SHOW_IMAGE,
    _match_frame_device_id,
    _match_skill_id,
    async_setup_intents,
)


def _make_device(hass, make_frame_entry, name: str, device_key: str):
    entry = make_frame_entry(device_key=device_key, entry_id=f"entry-{device_key}")
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    return dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_key)},
        name=name,
    )


async def test_no_frames_configured_raises(hass):
    with pytest.raises(HomeAssistantError, match="No Fraimic frames"):
        _match_frame_device_id(hass, "office")


async def test_exact_name_match(hass, make_frame_entry):
    office = _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _make_device(hass, make_frame_entry, "Kitchen Frame", "k2")

    assert _match_frame_device_id(hass, "Office Frame") == office.id


async def test_unambiguous_partial_match(hass, make_frame_entry):
    office = _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _make_device(hass, make_frame_entry, "Kitchen Frame", "k2")

    assert _match_frame_device_id(hass, "office") == office.id


async def test_ambiguous_partial_match_raises(hass, make_frame_entry):
    _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _make_device(hass, make_frame_entry, "Office Frame 2", "k2")

    with pytest.raises(HomeAssistantError, match="matches more than one frame"):
        _match_frame_device_id(hass, "office")


async def test_no_match_raises_with_configured_list(hass, make_frame_entry):
    _make_device(hass, make_frame_entry, "Office Frame", "k1")

    with pytest.raises(HomeAssistantError, match="No Fraimic frame matches"):
        _match_frame_device_id(hass, "garage")


async def test_intent_handler_success_calls_generate_ai_image_service(
    hass, make_frame_entry
):
    office = _make_device(hass, make_frame_entry, "Office Frame", "k1")
    await async_setup_intents(hass)

    calls = []

    async def _fake_service(call):
        calls.append(call.data)

    hass.services.async_register(DOMAIN, "generate_ai_image", _fake_service)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_GENERATE_AI_IMAGE,
        {"prompt": {"value": "a red barn"}, "frame": {"value": "Office"}},
    )

    assert response.error_code is None
    assert calls == [{"device_id": office.id, "prompt": "a red barn"}]


async def test_intent_handler_no_match_returns_no_valid_targets_error(hass):
    await async_setup_intents(hass)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_GENERATE_AI_IMAGE,
        {"prompt": {"value": "a red barn"}, "frame": {"value": "office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.NO_VALID_TARGETS


async def test_intent_handler_service_failure_surfaces_as_speech_error(
    hass, make_frame_entry
):
    _make_device(hass, make_frame_entry, "Office Frame", "k1")
    await async_setup_intents(hass)

    async def _failing_service(call):
        raise HomeAssistantError("no AI task entity configured")

    hass.services.async_register(DOMAIN, "generate_ai_image", _failing_service)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_GENERATE_AI_IMAGE,
        {"prompt": {"value": "a red barn"}, "frame": {"value": "Office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.FAILED_TO_HANDLE


# ---------------------------------------------------------------------------
# FraimicSendSkill: "send the word of the day to [frame]" -- works even with
# no prior mapping between the skill and the frame (that's the whole point).
# ---------------------------------------------------------------------------


class _FakeSkill:
    def __init__(self, skill_id, name):
        self.skill_id = skill_id
        self.name = name


class _FakeSkillManager:
    def __init__(self, skills):
        self.skills = {s.skill_id: s for s in skills}


def _register_skills(hass, *skills):
    hass.data.setdefault(DOMAIN, {})["_skills"] = _FakeSkillManager(skills)


async def test_match_skill_id_exact_and_partial(hass):
    _register_skills(
        hass,
        _FakeSkill("word_of_the_day", "Word of the Day"),
        _FakeSkill("joke_of_the_day", "Joke of the Day"),
    )
    assert _match_skill_id(hass, "Word of the Day") == "word_of_the_day"
    assert _match_skill_id(hass, "word") == "word_of_the_day"


async def test_match_skill_id_no_skills_configured_raises(hass):
    with pytest.raises(HomeAssistantError, match="No Fraimic skills"):
        _match_skill_id(hass, "word of the day")


async def test_send_skill_intent_success_calls_send_skill_service(
    hass, make_frame_entry
):
    office = _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _register_skills(hass, _FakeSkill("word_of_the_day", "Word of the Day"))
    await async_setup_intents(hass)

    calls = []

    async def _fake_service(call):
        calls.append(call.data)

    hass.services.async_register(DOMAIN, "send_skill", _fake_service)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SEND_SKILL,
        {"skill": {"value": "word of the day"}, "frame": {"value": "Office"}},
    )

    assert response.error_code is None
    assert calls == [{"device_id": office.id, "skill_id": "word_of_the_day"}]


async def test_send_skill_intent_unknown_skill_returns_no_valid_targets_error(
    hass, make_frame_entry
):
    _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _register_skills(hass, _FakeSkill("word_of_the_day", "Word of the Day"))
    await async_setup_intents(hass)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SEND_SKILL,
        {"skill": {"value": "recipe of the day"}, "frame": {"value": "Office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.NO_VALID_TARGETS


async def test_send_skill_intent_service_failure_surfaces_as_speech_error(
    hass, make_frame_entry
):
    _make_device(hass, make_frame_entry, "Office Frame", "k1")
    _register_skills(hass, _FakeSkill("word_of_the_day", "Word of the Day"))
    await async_setup_intents(hass)

    async def _failing_service(call):
        raise HomeAssistantError("renderer script unreachable")

    hass.services.async_register(DOMAIN, "send_skill", _failing_service)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SEND_SKILL,
        {"skill": {"value": "word of the day"}, "frame": {"value": "Office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.FAILED_TO_HANDLE


# ---------------------------------------------------------------------------
# FraimicShowImage: "show [image name] on [frame]"
# ---------------------------------------------------------------------------


class _FakeLibrary:
    def __init__(self, images=None):
        self.images = images or []

    async def async_list_images(self):
        return self.images

    async def async_get_bin_for_send(self, image_id, spec, pack_method=None, codec_id=None):
        return f"bin-for-{image_id}".encode()


def _register_library(hass, *images):
    lib = _FakeLibrary(list(images))
    hass.data.setdefault(DOMAIN, {})["_library"] = lib
    return lib


def _make_device_and_coordinator(hass, make_frame_entry, make_coordinator, name: str, device_key: str):
    entry = make_frame_entry(device_key=device_key, entry_id=f"entry-{device_key}")
    coordinator = make_coordinator(entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_key)},
        name=name,
    )
    return device, coordinator


async def test_show_image_intent_success_sends_image(
    hass, make_frame_entry, make_coordinator, monkeypatch
):
    office, coordinator = _make_device_and_coordinator(
        hass, make_frame_entry, make_coordinator, "Office Frame", "k1"
    )
    _register_library(hass, {"image_id": "mona_lisa_uuid", "filename": "mona_lisa.jpg"})
    await async_setup_intents(hass)

    calls = []

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        calls.append((image_bytes, image_id))
        return {"success": True, "queued": False}

    from custom_components.fraimic.coordinator import FraimicCoordinator
    monkeypatch.setattr(FraimicCoordinator, "async_send_image_or_queue", _fake_send)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SHOW_IMAGE,
        {"image_name": {"value": "mona lisa"}, "frame": {"value": "Office"}},
    )

    assert response.error_code is None
    assert calls == [(b"bin-for-mona_lisa_uuid", "mona_lisa_uuid")]


async def test_show_image_intent_no_match_returns_no_valid_targets(hass, make_frame_entry, make_coordinator):
    _make_device_and_coordinator(
        hass, make_frame_entry, make_coordinator, "Office Frame", "k1"
    )
    _register_library(hass)  # empty library
    await async_setup_intents(hass)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SHOW_IMAGE,
        {"image_name": {"value": "mona lisa"}, "frame": {"value": "Office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.NO_VALID_TARGETS


async def test_show_image_intent_service_failure_surfaces_as_speech_error(
    hass, make_frame_entry, make_coordinator, monkeypatch
):
    office, coordinator = _make_device_and_coordinator(
        hass, make_frame_entry, make_coordinator, "Office Frame", "k1"
    )
    _register_library(hass, {"image_id": "mona_lisa_uuid", "filename": "mona_lisa.jpg"})
    await async_setup_intents(hass)

    async def _failing_send(self, image_bytes, *, image_id=None, thumbnail=None):
        raise HomeAssistantError("frame connection timed out")

    from custom_components.fraimic.coordinator import FraimicCoordinator
    monkeypatch.setattr(FraimicCoordinator, "async_send_image_or_queue", _failing_send)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SHOW_IMAGE,
        {"image_name": {"value": "mona lisa"}, "frame": {"value": "Office"}},
    )

    assert response.error_code == ha_intent.IntentResponseErrorCode.FAILED_TO_HANDLE


async def test_show_image_intent_matches_voice_name(
    hass, make_frame_entry, make_coordinator, monkeypatch
):
    office, coordinator = _make_device_and_coordinator(
        hass, make_frame_entry, make_coordinator, "Office Frame", "k1"
    )
    # Register an image with a different filename but a matching voice name
    _register_library(
        hass,
        {"image_id": "img1", "filename": "photo_12345.png", "voice_name": "my profile pic"},
        {"image_id": "img2", "filename": "other.jpg", "voice_name": None},
    )
    await async_setup_intents(hass)

    calls = []

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        calls.append((image_bytes, image_id))
        return {"success": True, "queued": False}

    from custom_components.fraimic.coordinator import FraimicCoordinator
    monkeypatch.setattr(FraimicCoordinator, "async_send_image_or_queue", _fake_send)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SHOW_IMAGE,
        {"image_name": {"value": "my profile pic"}, "frame": {"value": "Office"}},
    )

    assert response.error_code is None
    assert calls == [(b"bin-for-img1", "img1")]


async def test_show_image_intent_tag_match_sends_random_tagged_image(
    hass, make_frame_entry, make_coordinator, monkeypatch
):
    office, coordinator = _make_device_and_coordinator(
        hass, make_frame_entry, make_coordinator, "Office Frame", "k1"
    )
    # 2 images with "Alyssa" tag, 1 with a different tag
    _register_library(
        hass,
        {"image_id": "alyssa_1", "filename": "1.jpg", "tags": ["Alyssa"]},
        {"image_id": "alyssa_2", "filename": "2.jpg", "tags": ["Alyssa"]},
        {"image_id": "other", "filename": "3.jpg", "tags": ["other"]},
    )
    await async_setup_intents(hass)

    calls = []

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        calls.append((image_bytes, image_id))
        return {"success": True, "queued": False}

    from custom_components.fraimic.coordinator import FraimicCoordinator
    monkeypatch.setattr(FraimicCoordinator, "async_send_image_or_queue", _fake_send)

    response = await ha_intent.async_handle(
        hass,
        "test",
        INTENT_SHOW_IMAGE,
        {"image_name": {"value": "Alyssa"}, "frame": {"value": "Office"}},
    )

    assert response.error_code is None
    assert len(calls) == 1
    assert calls[0][1] in ("alyssa_1", "alyssa_2")


