import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

WATER_LOW_THRESHOLD = 20


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SleepMe binary sensor entities."""
    device_id = config_entry.data.get("device_id")
    device_display_name = config_entry.data.get("display_name")
    update_manager = hass.data[DOMAIN][f"{device_id}_update_manager"]
    device_info_data = hass.data[DOMAIN]["device_info"]

    async_add_entities(
        [
            SleepMeWaterLevelBinarySensor(
                update_manager, device_id, device_display_name, device_info_data
            )
        ]
    )


class SleepMeWaterLevelBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a SleepMe water level binary sensor."""

    def __init__(self, coordinator, device_id, device_display_name, device_info_data):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_name = f"{device_display_name} Water Low"
        self._attr_unique_id = f"{device_id}_water_low"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": device_display_name,
            "manufacturer": MANUFACTURER,
            "model": device_info_data.get("model"),
            "sw_version": device_info_data.get("firmware_version"),
        }

    @property
    def is_on(self) -> bool:
        """Return true if the water level is low."""
        status = self.coordinator.data.get("status", {})
        water_level = status.get("water_level_percent", 100)
        return water_level < WATER_LOW_THRESHOLD