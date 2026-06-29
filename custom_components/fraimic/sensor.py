"""Sensor platform for the Fraimic integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FraimicCoordinator

from .const import CONF_NAME, DOMAIN


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fraimic sensors from a config entry."""
    coordinator: FraimicCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            FraimicBatterySensor(coordinator, entry),
            FraimicWifiRssiSensor(coordinator, entry),
            FraimicChargingSensor(coordinator, entry),
            FraimicFirmwareSensor(coordinator, entry),
            FraimicIpAddressSensor(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class FraimicBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class shared by all Fraimic sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        fw: str | None = None
        if self.coordinator.data:
            fw = self.coordinator.data.get("firmware_version")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.data[CONF_NAME],
            manufacturer="Fraimic",
            model="E-Ink Canvas",
            sw_version=fw,
        )


# ---------------------------------------------------------------------------
# Individual sensors
# ---------------------------------------------------------------------------


class FraimicBatterySensor(FraimicBaseSensor):
    """Battery level sensor (%)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_battery"
        self._attr_name = "Battery"

    @property
    def native_value(self) -> float | None:
        """Return the battery percentage.

        Newer "eframe" firmware reports a flat ``battery_pct`` key instead
        of the nested ``battery.percent`` structure used by older frames.
        """
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        try:
            return float(data["battery"]["percent"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            return float(data["battery_pct"])
        except (KeyError, TypeError, ValueError):
            return None


class FraimicWifiRssiSensor(FraimicBaseSensor):
    """WiFi signal strength sensor (dBm)."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_wifi_rssi"
        self._attr_name = "WiFi Signal"

    @property
    def native_value(self) -> int | None:
        """Return the RSSI value in dBm."""
        if not self.coordinator.data:
            return None
        try:
            return int(self.coordinator.data["wifi"]["rssi"])
        except (KeyError, TypeError, ValueError):
            return None


class FraimicChargingSensor(FraimicBaseSensor):
    """Charging state sensor (True / False)."""

    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_charging"
        self._attr_name = "Charging"

    @property
    def native_value(self) -> str | None:
        """Return charging state as a string."""
        if not self.coordinator.data:
            return None
        try:
            raw = self.coordinator.data["battery"]["charging"]
        except (KeyError, TypeError):
            return None

        # The API may return a bool or a string "True"/"False".
        if isinstance(raw, bool):
            return str(raw)
        return str(raw).capitalize()


class FraimicFirmwareSensor(FraimicBaseSensor):
    """Firmware version diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        self._attr_name = "Firmware"

    @property
    def native_value(self) -> str | None:
        """Return the firmware version string."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("firmware_version")


class FraimicIpAddressSensor(FraimicBaseSensor):
    """Current IP address diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: FraimicCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ip"
        self._attr_name = "IP Address"

    @property
    def native_value(self) -> str | None:
        """Return the frame's current IP address.

        Newer "eframe" firmware reports a flat ``ip_address`` key instead
        of the nested ``wifi.ip`` structure used by older frames.
        """
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        try:
            return data["wifi"]["ip"]
        except (KeyError, TypeError):
            pass
        return data.get("ip_address")
