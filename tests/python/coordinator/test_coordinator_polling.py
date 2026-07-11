"""Coordinator polling & IP self-healing (KPF 3).

If this silently breaks: sensors go "unavailable" forever after a router
reassigns the frame's IP, and the user thinks the frame is dead.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.fraimic.const import CONF_HOST, CONF_WIDTH, CONF_HEIGHT
from custom_components.fraimic.coordinator import _FAILURES_BEFORE_RESCAN


@pytest.fixture
def coordinator(make_coordinator, make_frame_entry):
    return make_coordinator(make_frame_entry())


async def test_successful_poll_updates_data_and_resets_failure_counter(
    hass, coordinator, aioclient_mock
):
    aioclient_mock.get(
        f"http://{coordinator.host}/api/info",
        json={"battery": 80, "width": 1200, "height": 1600},
    )
    coordinator._consecutive_failures = 2

    data = await coordinator._async_update_data()

    assert data["battery"] == 80
    assert coordinator._consecutive_failures == 0


async def test_connection_error_raises_update_failed_and_increments_counter(
    hass, coordinator, aioclient_mock
):
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=TimeoutError())

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._consecutive_failures == 1


async def test_http_error_status_raises_update_failed(hass, coordinator, aioclient_mock):
    aioclient_mock.get(f"http://{coordinator.host}/api/info", status=500)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_rescan_triggered_after_failure_threshold(
    hass, coordinator, aioclient_mock, monkeypatch
):
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=TimeoutError())

    rescan_calls = []

    async def _fake_rescan():
        rescan_calls.append(True)

    monkeypatch.setattr(coordinator, "_async_try_find_new_host", _fake_rescan)

    for _ in range(_FAILURES_BEFORE_RESCAN):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(rescan_calls) == 1, "rescan should fire exactly once at the threshold"


async def test_rescan_not_triggered_before_threshold(
    hass, coordinator, aioclient_mock, monkeypatch
):
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=TimeoutError())

    rescan_calls = []
    monkeypatch.setattr(
        coordinator, "_async_try_find_new_host", lambda: rescan_calls.append(True)
    )

    for _ in range(_FAILURES_BEFORE_RESCAN - 1):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert rescan_calls == []


async def test_rescan_finds_new_ip_and_updates_host(hass, coordinator, monkeypatch):
    coordinator._consecutive_failures = _FAILURES_BEFORE_RESCAN

    async def _fake_find(local_ip, device_key, session):
        return "192.168.1.99"

    monkeypatch.setattr(
        "custom_components.fraimic.coordinator.find_frame_by_device_key", _fake_find
    )
    monkeypatch.setattr(
        "custom_components.fraimic.coordinator.get_local_ip", lambda: "192.168.1.2"
    )
    monkeypatch.setattr(coordinator, "async_request_refresh", _noop)

    await coordinator._async_try_find_new_host()

    assert coordinator.host == "192.168.1.99"
    assert coordinator.config_entry.data[CONF_HOST] == "192.168.1.99"
    assert coordinator._consecutive_failures == 0


async def test_rescan_finds_nothing_leaves_host_unchanged(hass, coordinator, monkeypatch):
    original_host = coordinator.host

    async def _fake_find(local_ip, device_key, session):
        return None

    monkeypatch.setattr(
        "custom_components.fraimic.coordinator.find_frame_by_device_key", _fake_find
    )
    monkeypatch.setattr(
        "custom_components.fraimic.coordinator.get_local_ip", lambda: "192.168.1.2"
    )

    await coordinator._async_try_find_new_host()

    assert coordinator.host == original_host


async def test_dimension_change_is_persisted_to_entry_data(hass, coordinator, aioclient_mock):
    aioclient_mock.get(
        f"http://{coordinator.host}/api/info",
        json={"width": 1440, "height": 2560},
    )

    await coordinator._async_update_data()

    assert coordinator.config_entry.data[CONF_WIDTH] == 1440
    assert coordinator.config_entry.data[CONF_HEIGHT] == 2560


async def test_legacy_entry_backfills_device_key_and_mac(
    hass, make_coordinator, make_frame_entry, aioclient_mock
):
    coordinator = make_coordinator(make_frame_entry(device_key="", mac=""))
    aioclient_mock.get(
        f"http://{coordinator.host}/api/info",
        json={
            "device": {"device_key": "new-device-key"},
            "wifi": {"mac": "11:22:33:44:55:66"},
        },
    )

    await coordinator._async_update_data()

    assert coordinator.config_entry.data.get("device_key") == "new-device-key"
    assert coordinator.config_entry.data.get("mac_address") == "112233445566"


async def _noop(*args, **kwargs):
    return None
