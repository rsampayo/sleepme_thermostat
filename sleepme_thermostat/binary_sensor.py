import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat binary sensor from a config entry."""
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

    water_level_sensor = WaterLevelLowSensor(thermostat, device_id, name, hass)
    
    async_add_entities([water_level_sensor])

class WaterLevelLowSensor(BinarySensorEntity):
    def __init__(self, thermostat, device_id, name, hass):
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"{name} Water Level Low"  # Use the friendly name for the entity name
        self._attr_device_class = "problem"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_water_low"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": f"SleepMe {name}",
            "manufacturer": "SleepMe",
            "model": "Thermostat",
            "sw_version": "1.0",
        }
        self.hass = hass

    @property
    def is_on(self):
        """Return true if the water level is low."""
        return self._thermostat._is_water_low

    async def async_update(self):
        """Update the sensor state using the shared device status data."""
        _LOGGER.debug(f"[Device {self._device_id}] Water level status: {self.is_on}")
        self.async_write_ha_state()
