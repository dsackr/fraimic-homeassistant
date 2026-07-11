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
    _match_frame_device_id,
    async_register_intents,
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
    async_register_intents(hass)

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
    async_register_intents(hass)

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
    async_register_intents(hass)

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
