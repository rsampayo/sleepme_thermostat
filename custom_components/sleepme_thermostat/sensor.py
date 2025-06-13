import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SleepMe sensor entities."""
    device_id = config_entry.data.get("device_id")
    device_display_name = config_entry.data.get("display_name")
    update_manager = hass.data[DOMAIN][f"{device_id}_update_manager"]
    device_info_data = hass.data[DOMAIN]["device_info"]

    sensors = [
        SleepMeWaterLevelPercentSensor(update_manager, device_id, device_display_name, device_info_data),
        SleepMeSetTemperatureSensor(update_manager, device_id, device_display_name, device_info_data),
        SleepMeCurrentTemperatureSensor(update_manager, device_id, device_display_name, device_info_data),
    ]
    async_add_entities(sensors)


class BaseSleepMeSensor(CoordinatorEntity, SensorEntity):
    """Base class for SleepMe sensors."""

    def __init__(self, coordinator, device_id, device_display_name, device_info_data, sensor_name, unique_id_suffix):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_name = f"{device_display_name} {sensor_name}"
        self._attr_unique_id = f"{device_id}_{unique_id_suffix}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": device_display_name,
            "manufacturer": MANUFACTURER,
            "model": device_info_data.get("model"),
            "sw_version": device_info_data.get("firmware_version"),
        }


class SleepMeWaterLevelPercentSensor(BaseSleepMeSensor):
    """Representation of the water level percentage sensor."""

    def __init__(self, coordinator, device_id, device_display_name, device_info_data):
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_display_name, device_info_data, "Water Level", "water_level_percent")
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:water-percent"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        status = self.coordinator.data.get("status", {})
        return status.get("water_level_percent")


class SleepMeSetTemperatureSensor(BaseSleepMeSensor):
    """Representation of the set temperature sensor."""

    def __init__(self, coordinator, device_id, device_display_name, device_info_data):
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_display_name, device_info_data, "Set Temperature", "set_temp")
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self):
        """Return the state of the sensor."""
        status = self.coordinator.data.get("status", {})
        return status.get("set_temperature_c")


class SleepMeCurrentTemperatureSensor(BaseSleepMeSensor):
    """Representation of the current temperature sensor."""

    def __init__(self, coordinator, device_id, device_display_name, device_info_data):
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, device_display_name, device_info_data, "Current Temperature", "current_temp")
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self):
        """Return the state of the sensor."""
        status = self.coordinator.data.get("status", {})
        return status.get("current_temperature_c")