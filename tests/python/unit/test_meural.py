"""Meural local driver + JPEG codec (FramePort Phase 3 / KPF 32)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.fraimic.const import (
    API_SLEEP,
    CONF_DRIVER,
    CONF_HOST,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DOMAIN,
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
    parse_meural_system_stats,
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


def test_meural_orientation_prefers_gsensor():
    assert meural_orientation_from_payload(
        {"orientation": "landscape", "gsensor": "portrait"}
    ) == "portrait"
    assert meural_orientation_from_payload({"orientation": "portrait"}) == "portrait"
    assert meural_orientation_from_payload({"gsensor": "Landscape"}) == "landscape"
    assert meural_orientation_from_payload({"orientation": "upside_down"}) is None
    assert meural_orientation_from_payload(None) is None


def test_parse_meural_system_stats():
    stats = parse_meural_system_stats(
        {
            "backlight": "9",
            "lux": "42",
            "free_space": 3906,
            "wifi_status": {"name": "TheMachine", "signal": "-53"},
        }
    )
    assert stats["backlight"] == 9
    assert stats["lux"] == 42.0
    assert stats["free_space_mb"] == 3906
    assert stats["wifi_rssi"] == -53
    assert stats["wifi_ssid"] == "TheMachine"
    assert parse_meural_system_stats(None)["backlight"] is None


@pytest.mark.asyncio
async def test_follow_device_writes_orientation_option():
    hass = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {CONF_ORIENTATION_FOLLOW_DEVICE: True}
    coord = MeuralCoordinator(hass, entry)

    system = {
        "orientation": "portrait",
        "gsensor": "portrait",
        "version": "2.3.2_2.0.13",
        "backlight": "9",
        "lux": "0",
        "free_space": 3906,
        "wifi_status": {"ip": "192.168.1.32", "signal": "-53", "name": "LAN"},
    }

    with (
        patch(
            "custom_components.fraimic.meural_coordinator.probe_meural",
            new=AsyncMock(
                return_value={
                    "wifi_ip": "192.168.1.32",
                    "orientation": "portrait",
                    "host": "192.168.1.32",
                }
            ),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_system_info",
            new=AsyncMock(return_value=system),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_get_backlight",
            new=AsyncMock(return_value=9),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_is_sleeping",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data["device_orientation"] == ORIENTATION_PORTRAIT
    assert data["backlight"] == 9
    assert data["lux"] == 0.0
    assert data["free_space_mb"] == 3906
    assert data["wifi_rssi"] == -53
    assert data["sleeping"] is False
    assert data["ip_address"] == "192.168.1.32"
    assert hass.async_create_task.called
    coro = hass.async_create_task.call_args[0][0]
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
            "custom_components.fraimic.meural_coordinator.meural_get_backlight",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.meural_is_sleeping",
            new=AsyncMock(return_value=None),
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


@pytest.mark.asyncio
async def test_sleep_command_maps_to_suspend():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)
    coord.data = {"sleeping": False, "backlight": 9}

    with patch(
        "custom_components.fraimic.meural_coordinator.meural_suspend",
        new=AsyncMock(),
    ) as suspend:
        with patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ):
            status = await coord.async_send_command(API_SLEEP)
    assert status == 200
    suspend.assert_awaited_once()
    assert coord.data["sleeping"] is True


@pytest.mark.asyncio
async def test_restart_unsupported():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)
    with pytest.raises(HomeAssistantError, match="Restart"):
        await coord.async_send_command("/api/restart")


@pytest.mark.asyncio
async def test_set_backlight():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)
    coord.data = {"backlight": 9}
    with (
        patch(
            "custom_components.fraimic.meural_coordinator.meural_set_backlight",
            new=AsyncMock(),
        ) as set_bl,
        patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        await coord.async_set_backlight(40)
    set_bl.assert_awaited_once()
    assert coord.data["backlight"] == 40


@pytest.mark.asyncio
async def test_meural_unreachable_returns_offline_data_not_raise():
    """Probe miss must not raise — entry stays loaded for postcard sends."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)

    with (
        patch(
            "custom_components.fraimic.meural_coordinator.probe_meural",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.fraimic.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data["online"] is False
    assert data["ip_address"] == "192.168.1.32"


@pytest.mark.asyncio
async def test_orientation_change_redisplays_last_wire():
    """Physical rotate must re-postcard HA content, not leave app Recents."""
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {
        CONF_ORIENTATION_FOLLOW_DEVICE: True,
        CONF_ORIENTATION: ORIENTATION_LANDSCAPE,
    }
    coord = MeuralCoordinator(hass, entry)
    coord._last_wire_bytes = b"\xff\xd8\xffwirejpeg"
    coord.last_image_id = None

    with (
        patch.object(coord, "async_send_image", new=AsyncMock()) as send,
        patch.object(coord, "async_redisplay_last", wraps=coord.async_redisplay_last),
    ):
        await coord._async_maybe_follow_device_orientation(ORIENTATION_PORTRAIT)

    hass.config_entries.async_update_entry.assert_called_once()
    send.assert_awaited_once_with(b"\xff\xd8\xffwirejpeg")


@pytest.mark.asyncio
async def test_redisplay_prefers_library_image_id():
    hass = MagicMock()
    library = MagicMock()
    library.async_get_bin_for_send = AsyncMock(return_value=b"\xff\xd8\xfffromlib")
    hass.data = {DOMAIN: {"_library": library}}
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.data = {
        CONF_HOST: "192.168.1.32",
        CONF_DRIVER: DRIVER_MEURAL,
        "width": 1920,
        "height": 1080,
        "size": "meural",
    }
    entry.options = {CONF_ORIENTATION: ORIENTATION_PORTRAIT}
    coord = MeuralCoordinator(hass, entry)
    coord.last_image_id = "img-1"
    coord._last_wire_bytes = b"\xff\xd8\xffold"
    coord.last_thumbnail = b"thumb"

    with (
        patch.object(coord, "async_send_image", new=AsyncMock()) as send,
        patch.object(coord, "async_set_last_image", new=AsyncMock()) as set_last,
        patch(
            "custom_components.fraimic.panel_codec.panel_codec_for_entry",
            return_value=SimpleNamespace(id="jpeg_q90"),
        ),
        patch(
            "custom_components.fraimic.helpers.render_spec_for_entry",
            return_value=SimpleNamespace(width=1080, height=1920, variant="_c", locked=True, rotation=90),
        ),
    ):
        ok = await coord.async_redisplay_last()

    assert ok is True
    library.async_get_bin_for_send.assert_awaited_once()
    send.assert_awaited_once_with(b"\xff\xd8\xfffromlib")
    set_last.assert_awaited_once()
