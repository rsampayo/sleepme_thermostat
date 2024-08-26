import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat sensors from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")
    coordinator = hass.data[DOMAIN][f"{device_id}_update_manager"]

    _LOGGER.debug(f"[Device {device_id}] Setting up sensor platform from config entry.")

    thermostat = hass.data[DOMAIN].get(device_id)

    if thermostat is None:
        _LOGGER.error(f"[Device {device_id}] Thermostat entity not found!")
        hass.components.persistent_notification.create(
            f"The SleepMe Thermostat entity for device {device_id} was not found. Please check the configuration.",
            title="SleepMe Thermostat Error"
        )
        return

    # Create the sensors and add them
    ip_address_sensor = IPAddressSensor(coordinator, thermostat, device_id, name)
    lan_address_sensor = LANAddressSensor(coordinator, thermostat, device_id, name)
    brightness_level_sensor = BrightnessLevelSensor(coordinator, thermostat, device_id, name)
    display_temp_unit_sensor = DisplayTemperatureUnitSensor(coordinator, thermostat, device_id, name)
    time_zone_sensor = TimeZoneSensor(coordinator, thermostat, device_id, name)

    async_add_entities([
        ip_address_sensor, 
        lan_address_sensor, 
        brightness_level_sensor, 
        display_temp_unit_sensor, 
        time_zone_sensor
    ])

class IPAddressSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that indicates the IP address."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} IP Address"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_ip_address"
        self._attr_icon = "mdi:ip"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def state(self):
        """Return the IP address of the device."""
        return self.coordinator.data["about"].get("ip_address")

class LANAddressSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that indicates the LAN address."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} LAN Address"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_lan_address"
        self._attr_icon = "mdi:lan"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def state(self):
        """Return the LAN address of the device."""
        return self.coordinator.data["about"].get("lan_address")

class BrightnessLevelSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that indicates the brightness level."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} Brightness Level"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_brightness_level"
        self._attr_icon = "mdi:brightness-6"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = "%"  # Set unit to percentage

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def state(self):
        """Return the brightness level of the device."""
        return self.coordinator.data["control"].get("brightness_level")

class DisplayTemperatureUnitSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that indicates the display temperature unit."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} Display Temperature Unit"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_display_temperature_unit"
        self._attr_icon = "mdi:thermometer"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def state(self):
        """Return the display temperature unit of the device in uppercase."""
        temp_unit = self.coordinator.data["control"].get("display_temperature_unit")
        return temp_unit.upper() if temp_unit else None

class TimeZoneSensor(CoordinatorEntity, SensorEntity):
    """Representation of a sensor that indicates the time zone."""

    def __init__(self, coordinator, thermostat, device_id, name):
        super().__init__(coordinator)
        self._thermostat = thermostat
        self._device_id = device_id
        self._attr_name = f"Dock Pro {name} Time Zone"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_time_zone"
        self._attr_icon = "mdi:earth"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Reuse the device info from the thermostat entity
        self._attr_device_info = thermostat.device_info

    @property
    def state(self):
        """Return the time zone of the device."""
        return self.coordinator.data["control"].get("time_zone")