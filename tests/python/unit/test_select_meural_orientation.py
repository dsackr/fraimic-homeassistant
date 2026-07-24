"""Meural orientation select entity (KPF 32): choosing Follow/Portrait/
Landscape must persist the choice, but must not redisplay directly when the
selection actually changes something -- __init__.py's _async_update_listener
is the sole trigger for that (see test_meural.py's
test_async_update_listener_redisplays_once_on_orientation_change). Calling
async_redisplay_last() from both this entity and the listener used to
double-send the postcard on every orientation change.

Re-selecting the option that's already active is the one exception: HA's
async_update_entry is a no-op (and never invokes the listener) when the new
options dict is identical to what's already stored, so the entity must call
async_redisplay_last() itself in that case or a same-value reselect (e.g. to
force a re-postcard after Canvas drifted to a Recents thumbnail on its own)
would silently do nothing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.digital_frames.const import (
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from custom_components.digital_frames.select import MeuralOrientationSelect


def _make_select(options: dict) -> tuple[MeuralOrientationSelect, MagicMock, MagicMock]:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "meural_entry"
    entry.options = options
    coordinator = MagicMock()
    coordinator.data = {"device_orientation": ORIENTATION_LANDSCAPE}
    coordinator.async_set_device_orientation = AsyncMock()
    coordinator.async_redisplay_last = AsyncMock()

    select = MeuralOrientationSelect(coordinator, entry)
    select.hass = hass
    select.async_write_ha_state = MagicMock()  # unrelated HA plumbing
    return select, hass, coordinator


async def test_select_portrait_persists_option_without_redisplaying():
    select, hass, coordinator = _make_select(
        {CONF_ORIENTATION_FOLLOW_DEVICE: True}
    )

    await select.async_select_option("Portrait")

    hass.config_entries.async_update_entry.assert_called_once()
    updated_options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert updated_options[CONF_ORIENTATION] == ORIENTATION_PORTRAIT
    assert updated_options[CONF_ORIENTATION_FOLLOW_DEVICE] is False
    coordinator.async_redisplay_last.assert_not_awaited()


async def test_select_follow_persists_option_without_redisplaying():
    select, hass, coordinator = _make_select(
        {CONF_ORIENTATION_FOLLOW_DEVICE: False, CONF_ORIENTATION: ORIENTATION_PORTRAIT}
    )

    await select.async_select_option("Follow device")

    hass.config_entries.async_update_entry.assert_called_once()
    updated_options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert updated_options[CONF_ORIENTATION_FOLLOW_DEVICE] is True
    coordinator.async_redisplay_last.assert_not_awaited()


async def test_reselecting_already_active_orientation_forces_redisplay():
    # HA's async_update_entry never invokes _async_update_listener when the
    # new options dict is unchanged from the current one, so re-picking the
    # value already shown (e.g. to force a re-postcard after Canvas drifted
    # to a Recents thumbnail) must trigger the redisplay directly instead of
    # silently doing nothing.
    select, hass, coordinator = _make_select(
        {CONF_ORIENTATION_FOLLOW_DEVICE: False, CONF_ORIENTATION: ORIENTATION_PORTRAIT}
    )

    await select.async_select_option("Portrait")

    hass.config_entries.async_update_entry.assert_called_once()
    coordinator.async_redisplay_last.assert_awaited_once()


async def test_reselecting_already_active_follow_forces_redisplay():
    select, hass, coordinator = _make_select(
        {CONF_ORIENTATION_FOLLOW_DEVICE: True, CONF_ORIENTATION: ORIENTATION_LANDSCAPE}
    )
    # _make_select seeds coordinator.data's device_orientation as landscape,
    # matching CONF_ORIENTATION already stored -- a genuine no-op reselect.

    await select.async_select_option("Follow device")

    hass.config_entries.async_update_entry.assert_called_once()
    coordinator.async_redisplay_last.assert_awaited_once()
