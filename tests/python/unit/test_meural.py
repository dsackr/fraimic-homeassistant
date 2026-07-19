"""Meural local driver + JPEG codec (FramePort Phase 3 / KPF 32)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fraimic.const import (
    CONF_DRIVER,
    CONF_HOST,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DRIVER_MEURAL,
    MEURAL_SIZE_LABEL,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from custom_components.fraimic.panel_codec import (
    CODEC_JPEG_Q90,
    encode_for_panel,
    panel_codec_for_entry,
)
from custom_components.fraimic.meural import (
    meural_orientation_from_payload,
    probe_meural,
    send_meural_postcard,
)
from custom_components.fraimic.meural_coordinator import MeuralCoordinator


def test_panel_codec_for_meural_entry():
    entry = SimpleNamespace(
        entry_id="e1",
        data={
            CONF_DRIVER: DRIVER_MEURAL,
            "width": 1920,
            "height": 1080,
            "size": MEURAL_SIZE_LABEL,
        },
    )
    assert panel_codec_for_entry(entry).id == CODEC_JPEG_Q90
    assert panel_codec_for_entry(entry).preferred_payload == "jpeg"


def test_encode_jpeg_for_meural_geometry(sample_image_bytes):
    out = encode_for_panel(
        sample_image_bytes(400, 300),
        1920,
        1080,
        0,
        False,
        "fast",
        None,
        CODEC_JPEG_Q90,
    )
    # JPEG SOI marker
    assert out[:2] == b"\xff\xd8"
    assert len(out) > 100


def _mock_session(status: int, text: str):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.headers = {}
    resp.request_info = MagicMock()
    resp.history = ()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    session.post = MagicMock(return_value=cm)
    return session


@pytest.mark.asyncio
async def test_probe_meural_pass():
    session = _mock_session(
        200, '{"status":"pass","response":{"serial":"ABC","alias":"Room"}}'
    )
    info = await probe_meural(session, "192.168.1.80")
    assert info is not None
    assert info.get("serial") == "ABC"


@pytest.mark.asyncio
async def test_probe_meural_fail():
    session = _mock_session(200, '{"status":"fail","response":"nope"}')
    info = await probe_meural(session, "192.168.1.80")
    assert info is None


@pytest.mark.asyncio
async def test_send_meural_postcard_ok():
    session = _mock_session(200, '{"status":"pass","response":"ok"}')
    result = await send_meural_postcard(
        session, "192.168.1.80", b"\xff\xd8\xfffakejpeg"
    )
    assert result["status"] == "pass"


def test_meural_orientation_from_payload():
    assert meural_orientation_from_payload({"orientation": "portrait"}) == "portrait"
    assert meural_orientation_from_payload({"gsensor": "Landscape"}) == "landscape"
    assert meural_orientation_from_payload({"orientation": "upside_down"}) is None
    assert meural_orientation_from_payload(None) is None
    assert meural_orientation_from_payload("portrait") is None


@pytest.mark.asyncio
async def test_follow_device_writes_orientation_option():
    hass = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {CONF_ORIENTATION_FOLLOW_DEVICE: True}
    coord = MeuralCoordinator(hass, entry)

    identify = {
        "status": "pass",
        "response": {
            "wifi_ip": "192.168.1.32",
            "orientation": "portrait",
            "version": "2.3.2",
        },
    }
    # probe_meural unwraps response; mock at meural layer via coordinator imports
    system = {
        "orientation": "portrait",
        "gsensor": "portrait",
        "version": "2.3.2_2.0.13",
        "wifi_status": {"ip": "192.168.1.32"},
    }

    with (
        patch(
            "custom_components.fraimic.meural_coordinator.probe_meural",
            new=AsyncMock(return_value={**identify["response"], "host": "192.168.1.32"}),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_system_info",
            new=AsyncMock(return_value=system),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data["device_orientation"] == ORIENTATION_PORTRAIT
    assert data["ip_address"] == "192.168.1.32"
    # Task scheduled with coroutine for option write
    assert hass.async_create_task.called
    coro = hass.async_create_task.call_args[0][0]
    # Run the follow helper
    await coro
    hass.config_entries.async_update_entry.assert_called_once()
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["options"][CONF_ORIENTATION] == ORIENTATION_PORTRAIT
    assert kwargs["options"][CONF_ORIENTATION_FOLLOW_DEVICE] is True


@pytest.mark.asyncio
async def test_follow_device_skipped_when_manual_lock():
    hass = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {
        CONF_ORIENTATION_FOLLOW_DEVICE: False,
        CONF_ORIENTATION: ORIENTATION_LANDSCAPE,
    }
    coord = MeuralCoordinator(hass, entry)

    with (
        patch(
            "custom_components.fraimic.meural_coordinator.probe_meural",
            new=AsyncMock(
                return_value={"orientation": "portrait", "host": "192.168.1.32"}
            ),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_system_info",
            new=AsyncMock(return_value={"gsensor": "portrait"}),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data["device_orientation"] == ORIENTATION_PORTRAIT
    coro = hass.async_create_task.call_args[0][0]
    await coro
    hass.config_entries.async_update_entry.assert_not_called()
