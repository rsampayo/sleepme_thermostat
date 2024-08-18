import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat binary sensors from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")  # Retrieve the friendly name from the entry data
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
    water_level_sensor = WaterLevelLowSensor(thermostat, device_id, name)
    connected_sensor = DeviceConnectedBinarySensor(thermostat, device_id, name)

    async_add_entities([water_level_sensor, connected_sensor])

class WaterLevelLowSensor(BinarySensorEntity):
    """Representation of a binary sensor that indicates if the water level is low."""

    def __init__(self, thermostat, device_id, name):
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"{name} Water Level Low"  # Use the friendly name for the entity name
        self._attr_device_class = "problem"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_water_low"

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def is_on(self):
        """Return true if the water level is low."""
        return self._thermostat._is_water_low

    async def async_update(self):
        """Update the sensor state using the shared device status data."""
        _LOGGER.debug(f"[Device {self._device_id}] Water level status: {self.is_on}")
        self.async_write_ha_state()

class DeviceConnectedBinarySensor(BinarySensorEntity):
    """Representation of a binary sensor that indicates if the device is connected."""

    def __init__(self, thermostat, device_id, name):
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"{name} Connected"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_connected"
        self._attr_device_class = "connectivity"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC  # Categorize this sensor as diagnostic

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def is_on(self):
        """Return True if the device is connected, False otherwise."""
        return self._thermostat._is_connected

    async def async_update(self):
        """Fetch new state data for the binary sensor."""
        await self._thermostat.async_update()
        self.async_write_ha_state()
