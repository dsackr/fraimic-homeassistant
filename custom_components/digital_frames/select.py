"""Select platform for the Fraimic integration.

One entity per frame: an Orientation select.

**Fraimic / Spectra frames** — Auto / Portrait / Landscape:

"Auto" is the Fraimic way -- the frame accepts any picture, and a
mismatched-orientation image is displayed sideways at full size. Locking to
Portrait or Landscape makes every future send compose in that orientation:
mismatched images are auto-cropped (centered) so they stay upright, and if
the lock differs from the panel's native orientation the finished render is
rotated onto the native buffer (see helpers.render_spec_for_entry, plus the
"rotated hanging" edge option in the integration's Configure dialog for
clones mounted the non-Fraimic way).

**Meural frames** — Follow device / Portrait / Landscape:

Meural firmware reports hang orientation via gsensor on identify/system.
"Follow device" (default) copies that into the render lock so crop/send
match the physical hang. Portrait/Landscape pin a manual lock and stop
following until the user chooses Follow again.

Changing the selection applies to the NEXT image sent -- it does not re-push
whatever is currently on the frame.

The value is persisted in the config entry's options (not just entity
state), so the render pipeline -- which works from config entries, not
entities -- always sees it, including before this platform has loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DRIVER,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DOMAIN,
    DRIVER_MEURAL,
    ORIENTATION_AUTO,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from .sensor import frame_device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import DigitalFramesCoordinator

_OPTION_LABELS = {
    ORIENTATION_AUTO: "Auto (any picture, Fraimic default)",
    ORIENTATION_PORTRAIT: "Portrait",
    ORIENTATION_LANDSCAPE: "Landscape",
}
_LABEL_TO_VALUE = {label: value for value, label in _OPTION_LABELS.items()}

# Meural uses "follow" instead of Fraimic's unlocked "auto".
_MEURAL_FOLLOW = "follow"
_MEURAL_OPTION_LABELS = {
    _MEURAL_FOLLOW: "Follow device (gsensor)",
    ORIENTATION_PORTRAIT: "Portrait",
    ORIENTATION_LANDSCAPE: "Landscape",
}
_MEURAL_LABEL_TO_VALUE = {
    label: value for value, label in _MEURAL_OPTION_LABELS.items()
}


async def async_setup_entry(
    hass: "HomeAssistant",
    entry: "ConfigEntry",
    async_add_entities: "AddEntitiesCallback",
) -> None:
    """Set up the orientation select from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    from .const import DRIVER_SAMSUNG  # noqa: PLC0415

    if entry.data.get(CONF_DRIVER) == DRIVER_MEURAL:
        async_add_entities([MeuralOrientationSelect(coordinator, entry)])
        return
    if entry.data.get(CONF_DRIVER) == DRIVER_SAMSUNG:
        # Manual orientation lock for crop/send only (no gsensor follow yet).
        async_add_entities([DigitalFramesOrientationSelect(coordinator, entry)])
        return
    async_add_entities([DigitalFramesOrientationSelect(coordinator, entry)])


class DigitalFramesOrientationSelect(CoordinatorEntity, SelectEntity):
    """Per-frame orientation lock, persisted to the config entry options."""

    _attr_has_entity_name = True
    _attr_name = "Orientation"
    _attr_icon = "mdi:phone-rotate-portrait"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(_OPTION_LABELS.values())

    def __init__(
        self, coordinator: "DigitalFramesCoordinator", entry: "ConfigEntry"
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_orientation"

    @property
    def device_info(self) -> "DeviceInfo":
        return frame_device_info(self.hass, self.coordinator, self._entry)

    @property
    def current_option(self) -> str:
        value = self._entry.options.get(CONF_ORIENTATION, ORIENTATION_AUTO)
        return _OPTION_LABELS.get(value, _OPTION_LABELS[ORIENTATION_AUTO])

    async def async_select_option(self, option: str) -> None:
        value = _LABEL_TO_VALUE.get(option, ORIENTATION_AUTO)
        # Persisting to entry.options triggers the entry's update listener
        # (a reload) -- desired, so every send path immediately resolves the
        # new lock via render_spec_for_entry. Takes effect on the next image
        # sent; the frame's current picture is left alone.
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_ORIENTATION: value},
        )
        self.async_write_ha_state()


class MeuralOrientationSelect(CoordinatorEntity, SelectEntity):
    """Meural hang lock: follow gsensor (default) or pin portrait/landscape."""

    _attr_has_entity_name = True
    _attr_name = "Orientation"
    _attr_icon = "mdi:phone-rotate-portrait"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(_MEURAL_OPTION_LABELS.values())

    def __init__(
        self, coordinator: "DigitalFramesCoordinator", entry: "ConfigEntry"
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_orientation"

    @property
    def device_info(self) -> "DeviceInfo":
        return frame_device_info(self.hass, self.coordinator, self._entry)

    @property
    def current_option(self) -> str:
        follow = self._entry.options.get(CONF_ORIENTATION_FOLLOW_DEVICE, True)
        if follow:
            return _MEURAL_OPTION_LABELS[_MEURAL_FOLLOW]
        value = self._entry.options.get(CONF_ORIENTATION, ORIENTATION_PORTRAIT)
        if value not in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE):
            value = ORIENTATION_PORTRAIT
        return _MEURAL_OPTION_LABELS[value]

    async def async_select_option(self, option: str) -> None:
        value = _MEURAL_LABEL_TO_VALUE.get(option, _MEURAL_FOLLOW)
        if value == _MEURAL_FOLLOW:
            # Re-enable follow; seed lock from last gsensor reading if any.
            device = None
            if self.coordinator.data:
                device = self.coordinator.data.get("device_orientation")
            new_options = {
                **self._entry.options,
                CONF_ORIENTATION_FOLLOW_DEVICE: True,
            }
            if device in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE):
                new_options[CONF_ORIENTATION] = device
                # Align Canvas UI lock with physical hang when returning to follow.
                try:
                    await self.coordinator.async_set_device_orientation(device)
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                await self.coordinator.async_set_device_orientation(value)
            except Exception:  # noqa: BLE001
                pass
            new_options = {
                **self._entry.options,
                CONF_ORIENTATION: value,
                CONF_ORIENTATION_FOLLOW_DEVICE: False,
            }

        # Canvas may still show orientation-scoped Recents -- re-postcard.
        # That normally happens via __init__.py's _async_update_listener,
        # which fires for this exact option change; calling
        # async_redisplay_last() here too used to double-send the postcard
        # on every orientation change (two re-encodes, two POSTs, a visible
        # double-redraw flash) -- leave the listener as the single trigger
        # for an actual change. But HA's async_update_entry is a no-op (and
        # never invokes the listener) when new_options is identical to what
        # is already stored, so re-selecting the already-active option --
        # e.g. to force a re-postcard after Canvas drifted to a Recents
        # thumbnail on its own -- would otherwise silently do nothing.
        unchanged = new_options == dict(self._entry.options)
        self.hass.config_entries.async_update_entry(
            self._entry, options=new_options
        )
        if unchanged:
            await self.coordinator.async_redisplay_last()
        self.async_write_ha_state()
