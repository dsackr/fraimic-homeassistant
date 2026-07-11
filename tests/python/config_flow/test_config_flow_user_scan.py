"""Frame discovery & add-frame wizard (KPF 1).

If this silently breaks: users can't add frames at all, or duplicate
entries get created for the same physical frame.
"""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.fraimic.const import (
    CONF_DEVICE_KEY,
    CONF_HEIGHT,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_SIZE,
    CONF_WIDTH,
    DOMAIN,
)

FRAME_INFO = {
    "device": {"device_key": "abc123"},
    "wifi": {"mac": "aa:bb:cc:dd:ee:ff"},
    "width": 1200,
    "height": 1600,
}


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Config flow probing hits the network directly (not through
    aioclient_mock's registered-URL model, since scan_subnet fires up to
    254 concurrent probes) -- stub the helpers module-level functions
    config_flow.py imported instead."""
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.get_local_ip", lambda: "192.168.1.2"
    )


async def test_manual_host_entry_success_creates_entry(hass, monkeypatch):
    async def _probe(session, host, timeout=None):
        return FRAME_INFO if host == "192.168.1.50" else None

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.probe_device_size",
        lambda session, host: _async_none(),
    )
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.detect_frame_type_from_info",
        lambda info: None,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "name_device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Living Room Frame", "resolution": "13.3"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.50"
    assert result["data"][CONF_NAME] == "Living Room Frame"
    assert result["data"][CONF_WIDTH] == 1200
    assert result["data"][CONF_HEIGHT] == 1600
    assert result["data"][CONF_DEVICE_KEY] == "abc123"
    assert result["data"][CONF_MAC] == "aabbccddeeff"


async def test_manual_host_entry_cannot_connect(hass, monkeypatch):
    async def _probe(session, host, timeout=None):
        return None

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_HOST: "cannot_connect"}


async def test_auto_scan_no_host_finds_devices_and_proceeds_to_pick_device(
    hass, monkeypatch
):
    async def _scan(local_ip, session, **kwargs):
        return [{"ip": "192.168.1.50", "info": FRAME_INFO}]

    monkeypatch.setattr("custom_components.fraimic.config_flow.scan_subnet", _scan)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    # First visit auto-scans (user_input is None).
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pick_device"


async def test_auto_scan_no_devices_found_shows_error(hass, monkeypatch):
    async def _scan(local_ip, session, **kwargs):
        return []

    monkeypatch.setattr("custom_components.fraimic.config_flow.scan_subnet", _scan)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_devices_found"}


async def test_pick_device_manual_sentinel_goes_to_manual_step(hass, monkeypatch):
    async def _scan(local_ip, session, **kwargs):
        return [{"ip": "192.168.1.50", "info": FRAME_INFO}]

    monkeypatch.setattr("custom_components.fraimic.config_flow.scan_subnet", _scan)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "__manual__"}
    )
    assert result["step_id"] == "manual"


async def test_pick_device_selects_discovered_frame(hass, monkeypatch):
    async def _scan(local_ip, session, **kwargs):
        return [{"ip": "192.168.1.50", "info": FRAME_INFO}]

    monkeypatch.setattr("custom_components.fraimic.config_flow.scan_subnet", _scan)
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.probe_device_size",
        lambda session, host: _async_none(),
    )
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.detect_frame_type_from_info",
        lambda info: None,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "192.168.1.50"}
    )
    assert result["step_id"] == "name_device"


async def test_size_auto_detected_skips_resolution_field(hass, monkeypatch):
    async def _probe(session, host, timeout=None):
        return FRAME_INFO

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.probe_device_size",
        lambda session, host: _async_value("13.3"),
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["step_id"] == "name_device"
    assert "resolution" not in result["data_schema"].schema

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Kitchen Frame"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SIZE] == "13.3"


async def test_dhcp_discovery_matches_existing_entry_aborts(
    hass, make_frame_entry, monkeypatch
):
    entry = make_frame_entry(host="192.168.1.50", device_key="abc123", mac="aabbccddeeff")
    entry.add_to_hass(hass)

    async def _probe(session, host, timeout=None):
        return FRAME_INFO

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)

    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip="192.168.1.50",
            hostname="fraimic",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_dhcp_discovery_new_frame_proceeds_to_name_device(hass, monkeypatch):
    async def _probe(session, host, timeout=None):
        return FRAME_INFO

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)
    monkeypatch.setattr(
        "custom_components.fraimic.config_flow.probe_device_size",
        lambda session, host: _async_none(),
    )

    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip="192.168.1.50",
            hostname="fraimic",
            macaddress="aabbccddeeff",
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "name_device"


async def test_dhcp_discovery_non_fraimic_device_aborts(hass, monkeypatch):
    async def _probe(session, host, timeout=None):
        return None

    monkeypatch.setattr("custom_components.fraimic.config_flow.probe_frame", _probe)

    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip="192.168.1.77",
            hostname="not-a-frame",
            macaddress="112233445566",
        ),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "not_fraimic_device"


async def _async_none():
    return None


async def _async_value(v):
    return v
