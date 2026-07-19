"""resolve_frame_by_entity: Meural IP sensors + entry_id (KPF 32/5)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.http_api import resolve_frame_by_entity


def _coord(host="192.168.1.32"):
    c = MagicMock()
    c.async_send_image_or_queue = MagicMock()
    c.host = host
    return c


def test_resolve_by_entry_id_direct():
    hass = MagicMock()
    coord = _coord()
    entry = SimpleNamespace(entry_id="meural_entry", title="Kitchen Meural")
    hass.data = {DOMAIN: {"meural_entry": coord, "_library": object()}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    got_coord, got_entry = resolve_frame_by_entity(
        hass, None, entry_id="meural_entry"
    )
    assert got_coord is coord
    assert got_entry is entry


def test_resolve_prefers_entity_config_entry_id():
    hass = MagicMock()
    coord = _coord()
    entry = SimpleNamespace(entry_id="meural_entry", title="Kitchen Meural")
    hass.data = {DOMAIN: {"meural_entry": coord, "_library": object()}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    entity_entry = SimpleNamespace(
        config_entry_id="meural_entry",
        device_id=None,
        unique_id="meural_entry_ip",
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)

    with patch(
        "custom_components.digital_frames.http_api.er.async_get", return_value=ent_reg
    ):
        got_coord, got_entry = resolve_frame_by_entity(hass, "sensor.kitchen_meural_ip")

    assert got_coord is coord
    assert got_entry is entry


def test_resolve_from_unique_id_suffix_when_config_entry_id_missing():
    hass = MagicMock()
    coord = _coord()
    entry = SimpleNamespace(entry_id="abc123")
    hass.data = {DOMAIN: {"abc123": coord}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    entity_entry = SimpleNamespace(
        config_entry_id=None,
        device_id=None,
        unique_id="abc123_ip",
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)

    with patch(
        "custom_components.digital_frames.http_api.er.async_get", return_value=ent_reg
    ):
        got_coord, got_entry = resolve_frame_by_entity(hass, "sensor.meural_ip")

    assert got_coord is coord
    assert got_entry is entry


def test_resolve_skips_non_coordinator_domain_keys():
    hass = MagicMock()
    coord = _coord(host="192.168.1.1")
    entry = SimpleNamespace(entry_id="frame_entry")
    hass.data = {DOMAIN: {"frame_entry": coord, "_library": object()}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    entity_entry = SimpleNamespace(
        config_entry_id=None,
        device_id="dev1",
        unique_id="other_battery",
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)
    device_entry = SimpleNamespace(
        config_entries=["_library", "frame_entry"],
        identifiers={(DOMAIN, "frame_entry")},
    )
    dev_reg = MagicMock()
    dev_reg.async_get = MagicMock(return_value=device_entry)

    with (
        patch("custom_components.digital_frames.http_api.er.async_get", return_value=ent_reg),
        patch("custom_components.digital_frames.http_api.dr.async_get", return_value=dev_reg),
    ):
        got_coord, got_entry = resolve_frame_by_entity(hass, "sensor.frame_battery")

    assert got_coord is coord
    assert got_entry is entry


def test_resolve_missing_entity_raises():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=None)
    with patch(
        "custom_components.digital_frames.http_api.er.async_get", return_value=ent_reg
    ):
        with pytest.raises(ValueError, match="not found"):
            resolve_frame_by_entity(hass, "sensor.missing")


def test_resolve_no_coordinator_raises_clear_message():
    hass = MagicMock()
    hass.data = {DOMAIN: {"_library": object()}}
    entity_entry = SimpleNamespace(
        config_entry_id="gone", device_id=None, unique_id="gone_ip"
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)
    hass.config_entries.async_get_entry = MagicMock(return_value=None)
    with patch(
        "custom_components.digital_frames.http_api.er.async_get", return_value=ent_reg
    ):
        with pytest.raises(ValueError, match="No frame coordinator"):
            resolve_frame_by_entity(hass, "sensor.meural_ip")
