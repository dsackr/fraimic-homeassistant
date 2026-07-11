"""Options flow: scan interval, size backfill, orientation edge, 180-degree
flip (KPF 2).

If this silently breaks: settings don't stick, or the orientation lock
gets reset when saving unrelated fields.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.fraimic.const import (
    CONF_ORIENTATION,
    CONF_ROTATE_LANDSCAPE_180,
    CONF_ROTATION_EDGE,
    CONF_SIZE,
    EDGE_RIGHT,
    ORIENTATION_PORTRAIT,
)


async def test_default_form_reflects_current_options(hass, make_frame_entry):
    entry = make_frame_entry(size="13.3", options={"scan_interval": 120})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults["scan_interval"] == 120
    assert defaults["resolution"] == "13.3"


async def test_size_unset_leaves_unset_option_available(hass, make_frame_entry):
    entry = make_frame_entry(size="")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    resolution_key = next(k for k in schema if str(k) == "resolution")
    assert "" in schema[resolution_key].container


async def test_save_backfills_size_into_entry_data(hass, make_frame_entry):
    entry = make_frame_entry(size="")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 300,
            "resolution": "13.3",
            CONF_ROTATION_EDGE: "left",
            "rotate_portrait_180": False,
            "rotate_landscape_180": False,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SIZE] == "13.3"


async def test_orientation_lock_carried_through_unrelated_save(hass, make_frame_entry):
    entry = make_frame_entry(options={CONF_ORIENTATION: ORIENTATION_PORTRAIT})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 600,
            "resolution": "13.3",
            CONF_ROTATION_EDGE: EDGE_RIGHT,
            "rotate_portrait_180": False,
            "rotate_landscape_180": True,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ORIENTATION] == ORIENTATION_PORTRAIT
    assert result["data"][CONF_ROTATION_EDGE] == EDGE_RIGHT
    assert result["data"][CONF_ROTATE_LANDSCAPE_180] is True


async def test_scan_interval_below_minimum_rejected(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"]

    import pytest

    with pytest.raises(vol.Invalid):
        schema({"scan_interval": 10})
