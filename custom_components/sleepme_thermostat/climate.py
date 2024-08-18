import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat climate entity from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")
    coordinator = hass.data[DOMAIN][f"{device_id}_update_manager"]

    _LOGGER.debug(f"[Device {device_id}] Setting up SleepMeThermostat entity with name: {name}")
    thermostat = SleepMeThermostat(coordinator, device_id, name, entry.data)

    hass.data[DOMAIN][device_id] = thermostat
    async_add_entities([thermostat])

class SleepMeThermostat(CoordinatorEntity, ClimateEntity):
    def __init__(self, coordinator, device_id, name, device_info):
        super().__init__(coordinator)
        self._name = f"Dock Pro {name}"
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_thermostat"
        self._target_temperature = None

        # Set up device info attributes
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._name,
            "manufacturer": "SleepMe",
            "model": device_info.get("model"),
            "sw_version": device_info.get("firmware_version"),
            "connections": {("mac", device_info.get("mac_address"))},
        }

    @property
    def min_temp(self):
        return 12.5

    @property
    def max_temp(self):
        return 46.5

    @property
    def name(self):
        return self._name

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        return self.coordinator.data["status"].get("water_temperature_c")

    @property
    def target_temperature(self):
        return self._sanitize_temperature(self.coordinator.data["control"].get("set_temperature_c"))

    @property
    def hvac_mode(self):
        return self._determine_hvac_mode(self.coordinator.data["control"].get("thermal_control_status"))

    @property
    def hvac_modes(self):
        return [HVACMode.OFF, HVACMode.AUTO]

    @property
    def supported_features(self):
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.TURN_OFF
        )

    @property
    def extra_state_attributes(self):
        return {
            "is_water_low": self.coordinator.data["status"].get("is_water_low"),
            "is_connected": self.coordinator.data["status"].get("is_connected"),
        }

    @property
    def available(self):
        """Return True if the device is connected, False otherwise."""
        return self.coordinator.data["status"].get("is_connected", False)

    async def async_set_temperature(self, **kwargs):
        target_temp = kwargs.get("temperature")
        if target_temp is None:
            raise ValueError("Temperature is required")

        if target_temp < self.min_temp or target_temp > self.max_temp:
            _LOGGER.warning(f"[Device {self._device_id}] Temperature {target_temp}C is out of range.")
            return

        _LOGGER.info(f"[Device {self._device_id}] Setting target temperature to {target_temp}C")
        await self.coordinator.client.set_temp_level(target_temp)

        # Update internal state immediately
        self.coordinator.data["control"]["set_temperature_c"] = target_temp
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.AUTO:
            await self.coordinator.client.set_device_status("active")
        elif hvac_mode == HVACMode.OFF:
            await self.coordinator.client.set_device_status("standby")

        # Update internal state immediately
        self.coordinator.data["control"]["thermal_control_status"] = "active" if hvac_mode == HVACMode.AUTO else "standby"
        self.async_write_ha_state()

    def _sanitize_temperature(self, temp):
        """Sanitize temperature values returned by the API."""
        if temp == -1:
            _LOGGER.warning(f"[Device {self._device_id}] API returned -1, setting temperature to minimum allowed {self.min_temp}C.")
            return self.min_temp
        elif temp == 999:
            _LOGGER.warning(f"[Device {self._device_id}] API returned 999, setting temperature to maximum allowed {self.max_temp}C.")
            return self.max_temp
        return temp

    def _determine_hvac_mode(self, thermal_control_status):
        """Determine the HVAC mode based on the device's thermal control status."""
        if thermal_control_status == "active":
            return HVACMode.AUTO
        return HVACMode.OFF
