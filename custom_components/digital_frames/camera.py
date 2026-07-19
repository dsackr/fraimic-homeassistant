"""Camera platform for the Fraimic integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FraimicCoordinator
from .const import CONF_NAME, DOMAIN
from .sensor import frame_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fraimic cameras from a config entry."""
    coordinator: FraimicCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([FraimicCamera(coordinator, entry)])


class FraimicCamera(CoordinatorEntity[FraimicCoordinator], Camera):
    """Camera entity representing the Fraimic frame's photo display."""

    def __init__(self, coordinator: FraimicCoordinator, entry: ConfigEntry) -> None:
        """Initialise the camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self.entry = entry
        self._attr_name = f"{entry.data[CONF_NAME]} Display"
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._attr_device_info = frame_device_info(coordinator.hass, coordinator, entry)

    @property
    def is_on(self) -> bool:
        """Return true if camera is on."""
        return True

    @property
    def is_recording(self) -> bool:
        """Return true if the camera is recording."""
        return False

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current image bytes for the frame."""
        coordinator = self.coordinator
        thumbnail = getattr(coordinator, "last_thumbnail", None)
        if thumbnail is not None:
            return thumbnail

        image_id = getattr(coordinator, "last_image_id", None)
        if image_id is not None:
            from .library import _get_manager
            manager = _get_manager(self.hass)
            try:
                # Get a 480px thumbnail or the original
                thumbnail = await manager.async_get_thumbnail(image_id, 480)
                return thumbnail
            except Exception as err:
                _LOGGER.debug("Failed to get thumbnail for camera image: %s", err)
                try:
                    raw_bytes, _ = await manager.async_get_original(image_id)
                    return raw_bytes
                except Exception:
                    pass
        return None
