"""HA entities: sensors + Orientation select (KPF 21).

If this silently breaks: wrong/missing sensor values for a firmware shape
not yet seen, or selecting an orientation doesn't actually change
rendering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.digital_frames.const import CONF_ORIENTATION, DOMAIN
from custom_components.digital_frames.sensor import (
    FraimicBatterySensor,
    FraimicChargingSensor,
    FraimicFirmwareSensor,
    FraimicIpAddressSensor,
    FraimicQueuedSendSensor,
    FraimicWifiRssiSensor,
    frame_device_info,
)


def _fake_coordinator(data=None, pending_send=None):
    return SimpleNamespace(data=data, pending_send=pending_send)


# ---------------------------------------------------------------------------
# Battery sensor -- old (nested) vs new ("eframe") firmware shapes
# ---------------------------------------------------------------------------


def test_battery_nested_shape(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicBatterySensor(_fake_coordinator({"battery": {"percent": 87}}), entry)
    assert sensor.native_value == 87.0


def test_battery_flat_eframe_shape(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicBatterySensor(_fake_coordinator({"battery_pct": 42}), entry)
    assert sensor.native_value == 42.0


def test_battery_missing_data_returns_none(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicBatterySensor(_fake_coordinator(None), entry)
    assert sensor.native_value is None
    sensor2 = FraimicBatterySensor(_fake_coordinator({}), entry)
    assert sensor2.native_value is None


# ---------------------------------------------------------------------------
# WiFi RSSI
# ---------------------------------------------------------------------------


def test_wifi_rssi_present(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicWifiRssiSensor(_fake_coordinator({"wifi": {"rssi": -55}}), entry)
    assert sensor.native_value == -55


def test_wifi_rssi_missing_returns_none(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicWifiRssiSensor(_fake_coordinator({}), entry)
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# Charging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [(True, "True"), (False, "False"), ("true", "True"), ("false", "False")],
)
def test_charging_bool_and_string_shapes(make_frame_entry, raw, expected):
    entry = make_frame_entry()
    sensor = FraimicChargingSensor(
        _fake_coordinator({"battery": {"charging": raw}}), entry
    )
    assert sensor.native_value == expected


def test_charging_missing_returns_none(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicChargingSensor(_fake_coordinator({}), entry)
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# Firmware / IP address (nested vs flat "eframe" shapes)
# ---------------------------------------------------------------------------


def test_firmware_present(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicFirmwareSensor(_fake_coordinator({"firmware_version": "1.2.3"}), entry)
    assert sensor.native_value == "1.2.3"


def test_ip_address_nested_shape(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicIpAddressSensor(
        _fake_coordinator({"wifi": {"ip": "192.168.1.50"}}), entry
    )
    assert sensor.native_value == "192.168.1.50"


def test_ip_address_flat_eframe_shape(make_frame_entry):
    entry = make_frame_entry()
    sensor = FraimicIpAddressSensor(
        _fake_coordinator({"ip_address": "192.168.1.60"}), entry
    )
    assert sensor.native_value == "192.168.1.60"


# ---------------------------------------------------------------------------
# Queued-send sensor
# ---------------------------------------------------------------------------


def test_queued_send_sensor_reflects_pending_state(make_frame_entry):
    entry = make_frame_entry()
    idle = FraimicQueuedSendSensor(_fake_coordinator(pending_send=None), entry)
    assert idle.native_value == "idle"
    queued = FraimicQueuedSendSensor(_fake_coordinator(pending_send={"token": "x"}), entry)
    assert queued.native_value == "queued"


# ---------------------------------------------------------------------------
# Device info fallback when no frame_type registered for CONF_SIZE
# ---------------------------------------------------------------------------


async def test_device_info_falls_back_for_unregistered_size(hass, make_frame_entry):
    entry = make_frame_entry(size="not-a-real-size")
    device_info = frame_device_info(hass, _fake_coordinator({}), entry)
    assert device_info["manufacturer"] == "Fraimic"
    assert device_info["model"] == "E-Ink Canvas"


async def test_device_info_uses_registered_frame_type(hass, make_frame_entry):
    entry = make_frame_entry(size="7.3")
    device_info = frame_device_info(hass, _fake_coordinator({}), entry)
    assert device_info["manufacturer"] == "Community (Fraimic-compatible)"


# ---------------------------------------------------------------------------
# Orientation select round-trip (via real entry setup)
# ---------------------------------------------------------------------------


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
            return {"battery": {"percent": 90}, "width": 1200, "height": 1600}

    class _FakeSession:
        def get(self, *a, **kw):
            return _FakeResponse()

        def post(self, *a, **kw):
            return _FakeResponse()

    monkeypatch.setattr(
        "custom_components.digital_frames.coordinator.async_get_clientsession",
        lambda hass: _FakeSession(),
    )


async def test_orientation_select_persists_to_entry_options(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_orientation")
    assert entity_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "Portrait"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.options.get(CONF_ORIENTATION) == "portrait"


async def test_orientation_select_default_is_auto(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_orientation")
    state = hass.states.get(entity_id)
    assert state.state == "Auto (any picture, Fraimic default)"


# ---------------------------------------------------------------------------
# Camera entity
# ---------------------------------------------------------------------------


async def test_camera_entity_setup(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("camera", DOMAIN, f"{entry.entry_id}_camera")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "idle"
    assert state.name == f"{entry.data['name']} Display"


async def test_camera_image_returns_coordinator_thumbnail(hass, make_frame_entry):
    from custom_components.digital_frames.camera import FraimicCamera
    entry = make_frame_entry()
    coordinator = _fake_coordinator(pending_send=None)
    coordinator.hass = hass
    coordinator.last_thumbnail = b"png-bytes"
    coordinator.last_image_id = None

    camera = FraimicCamera(coordinator, entry)
    img = await camera.async_camera_image()
    assert img == b"png-bytes"
