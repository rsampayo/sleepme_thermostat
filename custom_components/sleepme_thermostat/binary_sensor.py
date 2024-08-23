import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat binary sensors from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")
    coordinator = hass.data[DOMAIN][f"{device_id}_update_manager"]

    _LOGGER.debug(f"[Device {device_id}] Setting up binary sensor platform from config entry.")

    thermostat = hass.data[DOMAIN].get(device_id)

    if thermostat is None:
        _LOGGER.error(f"[Device {device_id}] Thermostat entity not found!")
        hass.components.persistent_notification.create(
            f"The SleepMe Thermostat entity for device {device_id} was not found. Please check the configuration.",
            title="SleepMe Thermostat Error"
        )
        return

    # Create the sensors and add them
    water_level_sensor = WaterLevelLowSensor(coordinator, thermostat, device_id, name)
    connected_sensor = DeviceConnectedBinarySensor(coordinator, thermostat, device_id, name)

    async_add_entities([water_level_sensor, connected_sensor])

class WaterLevelLowSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a binary sensor that indicates if the water level is low."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} Water Level"
        self._attr_device_class = "problem"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_water_low"

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def is_on(self):
        """Return true if the water level is low."""
        return self.coordinator.data["status"].get("is_water_low")

class DeviceConnectedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a binary sensor that indicates if the device is connected."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} Connected"
        self._attr_device_class = "connectivity"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_connected"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def is_on(self):
        """Return true if the device is connected."""
        return self.coordinator.data["status"].get("is_connected")
