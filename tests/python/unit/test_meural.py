"""Meural local driver + JPEG codec (FramePort Phase 3 / KPF 32)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.digital_frames.const import (
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
from custom_components.digital_frames.panel_codec import (
    CODEC_JPEG_Q90,
    encode_for_panel,
    panel_codec_for_entry,
)
from custom_components.digital_frames.meural import (
    meural_orientation_from_payload,
    meural_unique_id,
    parse_meural_system_stats,
    probe_meural,
    send_meural_postcard,
)
from custom_components.digital_frames.meural_coordinator import MeuralCoordinator


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


def test_meural_unique_id_prefers_serial():
    assert meural_unique_id({"serial": "ABC123"}, "192.168.1.80") == "meural:ABC123"
    assert (
        meural_unique_id({"serialNumber": "SN9"}, "192.168.1.80") == "meural:SN9"
    )
    assert meural_unique_id({"mac": "aa:bb"}, "192.168.1.80") == "meural:aa:bb"
    assert meural_unique_id({}, "192.168.1.80") == "meural:192.168.1.80"
    assert meural_unique_id(None, "10.0.0.5") == "meural:10.0.0.5"


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
async def test_scan_subnet_dual_probe_meural(monkeypatch):
    """include_meural falls through to Meural probe when Fraimic misses."""
    from custom_components.digital_frames.const import DRIVER_MEURAL
    from custom_components.digital_frames import helpers as helpers_mod

    async def _probe_frame(session, host, timeout=None):
        return None

    async def _probe_meural(session, host, *, timeout=None):
        if host == "192.168.1.80":
            return {"serial": "MEU1", "host": host}
        return None

    monkeypatch.setattr(helpers_mod, "probe_frame", _probe_frame)
    monkeypatch.setattr(
        "custom_components.digital_frames.meural.probe_meural", _probe_meural
    )

    # Only probe a single host by shrinking the "subnet" via a fake host list.
    # scan_subnet builds /24 from host_ip — monkeypatch gather path by
    # overriding IPv4Network hosts via a narrow local range is hard; instead
    # call the bounded probe logic through scan_subnet with concurrency and
    # accept full /24 (254 probes) with instant mocks.
    found = await helpers_mod.scan_subnet(
        "192.168.1.2", object(), concurrency=254, include_meural=True
    )
    meurals = [f for f in found if f.get("driver") == DRIVER_MEURAL]
    assert len(meurals) == 1
    assert meurals[0]["ip"] == "192.168.1.80"
    assert meurals[0]["info"]["serial"] == "MEU1"


@pytest.mark.asyncio
async def test_scan_subnet_meural_off_by_default(monkeypatch):
    from custom_components.digital_frames import helpers as helpers_mod

    async def _probe_frame(session, host, timeout=None):
        return None

    called = {"n": 0}

    async def _probe_meural(session, host, *, timeout=None):
        called["n"] += 1
        return {"serial": "X"}

    monkeypatch.setattr(helpers_mod, "probe_frame", _probe_frame)
    monkeypatch.setattr(
        "custom_components.digital_frames.meural.probe_meural", _probe_meural
    )

    found = await helpers_mod.scan_subnet(
        "192.168.1.2", object(), concurrency=254, include_meural=False
    )
    assert found == []
    assert called["n"] == 0


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
            "custom_components.digital_frames.meural_coordinator.probe_meural",
            new=AsyncMock(
                return_value={
                    "wifi_ip": "192.168.1.32",
                    "orientation": "portrait",
                    "host": "192.168.1.32",
                }
            ),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_system_info",
            new=AsyncMock(return_value=system),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_get_backlight",
            new=AsyncMock(return_value=9),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_is_sleeping",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.async_get_clientsession",
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
            "custom_components.digital_frames.meural_coordinator.probe_meural",
            new=AsyncMock(
                return_value={"orientation": "portrait", "host": "192.168.1.32"}
            ),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_system_info",
            new=AsyncMock(return_value={"gsensor": "portrait"}),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_get_backlight",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_is_sleeping",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.async_get_clientsession",
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
        "custom_components.digital_frames.meural_coordinator.meural_suspend",
        new=AsyncMock(),
    ) as suspend:
        with patch(
            "custom_components.digital_frames.meural_coordinator.async_get_clientsession",
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
            "custom_components.digital_frames.meural_coordinator.meural_set_backlight",
            new=AsyncMock(),
        ) as set_bl,
        patch(
            "custom_components.digital_frames.meural_coordinator.async_get_clientsession",
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
            "custom_components.digital_frames.meural_coordinator.probe_meural",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data["online"] is False
    assert data["ip_address"] == "192.168.1.32"


@pytest.mark.asyncio
async def test_orientation_change_updates_options_without_redisplaying_directly():
    """Physical rotate must persist the new orientation, but must NOT
    redisplay from here -- __init__.py's _async_update_listener is the sole
    trigger for that (see test_async_update_listener_redisplays_once_on_
    orientation_change below). Calling async_redisplay_last() from both
    this method and the listener used to double-send the postcard on every
    physical rotate: two full re-encodes, two POSTs, a visible
    double-redraw flash."""
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
        patch.object(
            coord, "async_redisplay_last", new=AsyncMock()
        ) as redisplay,
    ):
        await coord._async_maybe_follow_device_orientation(ORIENTATION_PORTRAIT)

    hass.config_entries.async_update_entry.assert_called_once()
    updated_options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert updated_options[CONF_ORIENTATION] == ORIENTATION_PORTRAIT
    redisplay.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_update_listener_redisplays_once_on_orientation_change():
    """The single source of truth for orientation-driven redisplay: fires
    exactly once when CONF_ORIENTATION/CONF_ORIENTATION_FOLLOW_DEVICE
    actually change, and not at all for an unrelated option change or a
    repeat call with nothing new."""
    from custom_components.digital_frames import _async_update_listener

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.options = {CONF_ORIENTATION: ORIENTATION_LANDSCAPE, "unrelated": 1}

    coord = MagicMock()
    coord.host = "192.168.1.32"
    coord.async_send_image_or_queue = AsyncMock()
    coord.async_redisplay_last = AsyncMock()
    hass.data[DOMAIN]["meural_entry"] = coord

    # First call only seeds the snapshot -- no prior state to diff against.
    await _async_update_listener(hass, entry)
    coord.async_redisplay_last.assert_not_awaited()

    # Orientation changes -- must redisplay exactly once.
    entry.options = {**entry.options, CONF_ORIENTATION: ORIENTATION_PORTRAIT}
    await _async_update_listener(hass, entry)
    coord.async_redisplay_last.assert_awaited_once()

    # An unrelated option changing must not trigger another redisplay.
    entry.options = {**entry.options, "unrelated": 2}
    await _async_update_listener(hass, entry)
    coord.async_redisplay_last.assert_awaited_once()


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
            "custom_components.digital_frames.panel_codec.panel_codec_for_entry",
            return_value=SimpleNamespace(id="jpeg_q90"),
        ),
        patch(
            "custom_components.digital_frames.helpers.render_spec_for_entry",
            return_value=SimpleNamespace(width=1080, height=1920, variant="_c", locked=True, rotation=90),
        ),
    ):
        ok = await coord.async_redisplay_last()

    assert ok is True
    library.async_get_bin_for_send.assert_awaited_once()
    send.assert_awaited_once_with(b"\xff\xd8\xfffromlib")
    set_last.assert_awaited_once()
