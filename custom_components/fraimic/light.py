"""Light platform — Meural Canvas backlight (local only).

Fraimic Spectra frames are e‑ink and have no continuous backlight, so this
platform only creates entities for ``driver=meural`` entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DRIVER, DOMAIN, DRIVER_MEURAL
from .sensor import frame_device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .meural_coordinator import MeuralCoordinator


async def async_setup_entry(
    hass: "HomeAssistant",
    entry: "ConfigEntry",
    async_add_entities: "AddEntitiesCallback",
) -> None:
    # Only Meural exposes a continuous backlight light entity.
    if entry.data.get(CONF_DRIVER) != DRIVER_MEURAL:
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeuralBacklightLight(coordinator, entry)])


class MeuralBacklightLight(CoordinatorEntity, LightEntity):
    """Meural display backlight as a brightness-capable light.

    On/off maps to resume/suspend (display sleep). Brightness maps to
    ``control_command/set_backlight/{0-100}``.
    """

    _attr_has_entity_name = True
    _attr_name = "Backlight"
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, coordinator: "MeuralCoordinator", entry: "ConfigEntry"
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_backlight"

    @property
    def device_info(self) -> "DeviceInfo":
        return frame_device_info(self.hass, self.coordinator, self._entry)

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        if data.get("sleeping") is True:
            return False
        return True

    @property
    def brightness(self) -> int | None:
        """HA brightness 0–255 from Meural 0–100."""
        data = self.coordinator.data or {}
        level = data.get("backlight")
        if level is None:
            return None
        try:
            level_i = max(0, min(100, int(level)))
        except (TypeError, ValueError):
            return None
        return round(level_i * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        data = self.coordinator.data or {}
        if data.get("sleeping"):
            await self.coordinator.async_resume()
        if ATTR_BRIGHTNESS in kwargs:
            ha_b = int(kwargs[ATTR_BRIGHTNESS])
            level = max(0, min(100, round(ha_b * 100 / 255)))
            await self.coordinator.async_set_backlight(level)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        await self.coordinator.async_suspend()
        self.async_write_ha_state()
