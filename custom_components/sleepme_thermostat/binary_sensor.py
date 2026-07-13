"""Binary sensors for SleepMe devices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import build_device_info, is_sleep_tracker

if TYPE_CHECKING:
    from .update_manager import SleepMeUpdateManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SleepMe binary sensors from a config entry."""
    device_id: str = entry.data["device_id"]
    data = entry.runtime_data
    device_info = build_device_info(device_id, entry.title, data.device_info)

    entities: list[BinarySensorEntity] = [
        DeviceConnectedBinarySensor(data.coordinator, device_id, device_info)
    ]
    if is_sleep_tracker(entry.data.get("model")):
        entities.append(
            UserDetectedBinarySensor(data.coordinator, device_id, device_info)
        )
    else:
        entities.append(WaterLevelLowSensor(data.coordinator, device_id, device_info))
    async_add_entities(entities)


class WaterLevelLowSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor: water level low."""

    _attr_has_entity_name = True
    _attr_name = "Water Level"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_water_low"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if the water level is low."""
        return self.coordinator.data["status"].get("is_water_low")


class DeviceConnectedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor: device connectivity."""

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_connected"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if the device is connected."""
        return self.coordinator.data["status"].get("is_connected")


class UserDetectedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor: the tracker currently detects a sleeper in bed."""

    _attr_has_entity_name = True
    _attr_name = "Bed Occupancy"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_user_detected"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        """Return true while the tracker detects a user."""
        return self.coordinator.data["status"].get("user_detected")
