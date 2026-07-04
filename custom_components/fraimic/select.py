"""Select platform for the Fraimic integration.

One entity per frame: an Orientation select (Auto / Portrait / Landscape).

"Auto" is the Fraimic way -- the frame accepts any picture, and a
mismatched-orientation image is displayed sideways at full size. Locking to
Portrait or Landscape makes every future send compose in that orientation:
mismatched images are auto-cropped (centered) so they stay upright, and if
the lock differs from the panel's native orientation the finished render is
rotated onto the native buffer (see helpers.render_spec_for_entry, plus the
"rotated hanging" edge option in the integration's Configure dialog for
clones mounted the non-Fraimic way).

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
    CONF_ORIENTATION,
    DOMAIN,
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

    from .coordinator import FraimicCoordinator

_OPTION_LABELS = {
    ORIENTATION_AUTO: "Auto (any picture, Fraimic default)",
    ORIENTATION_PORTRAIT: "Portrait",
    ORIENTATION_LANDSCAPE: "Landscape",
}
_LABEL_TO_VALUE = {label: value for value, label in _OPTION_LABELS.items()}


async def async_setup_entry(
    hass: "HomeAssistant",
    entry: "ConfigEntry",
    async_add_entities: "AddEntitiesCallback",
) -> None:
    """Set up the Fraimic orientation select from a config entry."""
    coordinator: "FraimicCoordinator" = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FraimicOrientationSelect(coordinator, entry)])


class FraimicOrientationSelect(CoordinatorEntity, SelectEntity):
    """Per-frame orientation lock, persisted to the config entry options."""

    _attr_has_entity_name = True
    _attr_name = "Orientation"
    _attr_icon = "mdi:phone-rotate-portrait"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(_OPTION_LABELS.values())

    def __init__(
        self, coordinator: "FraimicCoordinator", entry: "ConfigEntry"
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
