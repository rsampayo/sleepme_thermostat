import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from .sleepme import SleepMeClient
from .const import DOMAIN, API_URL  # Import the DOMAIN and API_URL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat climate entity from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")

    sleepme_controller = SleepMeClient(API_URL, entry.data.get("api_token"), device_id)
    thermostat = SleepMeThermostat(sleepme_controller, device_id, name)
    
    hass.data[DOMAIN][device_id] = thermostat
    async_add_entities([thermostat])

class SleepMeThermostat(ClimateEntity):
    def __init__(self, controller, device_id, name):
        self._controller = controller
        self._name = f"SleepMe {name}"
        self._device_id = device_id
        self._target_temperature = None
        self._hvac_mode = HVACMode.OFF
        self._supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._current_temperature = None
        self._is_water_low = False
        self._attr_unique_id = f"{DOMAIN}_{device_id}_thermostat"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._name,
            "manufacturer": "SleepMe",
            "model": "Thermostat",
            "sw_version": "1.0",
        }

    @property
    def name(self):
        return self._name

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        return self._current_temperature

    @property
    def target_temperature(self):
        return self._target_temperature

    @property
    def hvac_mode(self):
        return self._hvac_mode

    @property
    def hvac_modes(self):
        return [HVACMode.OFF, HVACMode.AUTO]

    @property
    def supported_features(self):
        return self._supported_features

    @property
    def extra_state_attributes(self):
        return {
            "is_water_low": self._is_water_low,
        }

    @property
    def min_temp(self):
        return 13

    @property
    def max_temp(self):
        return 46

    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs:
            target_temp = kwargs["temperature"]
            if target_temp < self.min_temp or target_temp > self.max_temp:
                _LOGGER.warning(f"Temperature {target_temp}C is out of range. Must be between {self.min_temp}C and {self.max_temp}C.")
                return
            self._target_temperature = target_temp
            _LOGGER.info(f"Set target temperature to {self._target_temperature}")
            await self._controller.set_temp_level(self._target_temperature)

    async def async_set_hvac_mode(self, hvac_mode):
        self._hvac_mode = hvac_mode
        _LOGGER.info(f"Set HVAC mode to {self._hvac_mode}")
        if hvac_mode == HVACMode.AUTO:
            await self._controller.set_device_status("active")
        elif hvac_mode == HVACMode.OFF:
            await self._controller.set_device_status("standby")

    async def async_update(self):
        # Make the API call to get the device status
        device_status = await self._controller.get_device_status()
        _LOGGER.debug(f"Device status response: {device_status}")
        
        # Update the climate entity attributes
        current_temp = device_status.get("status", {}).get("water_temperature_c")
        set_temp = device_status.get("control", {}).get("set_temperature_c")
        
        if current_temp == -1:
            current_temp = self.min_temp
            _LOGGER.warning(f"API returned -1, setting current temperature to minimum allowed {self.min_temp}C.")
        elif current_temp == 999:
            current_temp = self.max_temp
            _LOGGER.warning(f"API returned 999, setting current temperature to maximum allowed {self.max_temp}C.")
        
        if set_temp == -1:
            set_temp = self.min_temp
            _LOGGER.warning(f"API returned -1, setting set temperature to minimum allowed {self.min_temp}C.")
        elif set_temp == 999:
            set_temp = self.max_temp
            _LOGGER.warning(f"API returned 999, setting set temperature to maximum allowed {self.max_temp}C.")
        
        self._current_temperature = current_temp
        self._target_temperature = set_temp
        
        thermal_control_status = device_status.get("control", {}).get("thermal_control_status")
        self._is_water_low = device_status.get("status", {}).get("is_water_low", False)
        
        new_hvac_mode = HVACMode.OFF
        
        if thermal_control_status == "active":
            new_hvac_mode = HVACMode.AUTO
        elif thermal_control_status == "standby":
            new_hvac_mode = HVACMode.OFF
        
        if new_hvac_mode != self._hvac_mode:
            _LOGGER.info(f"HVAC mode changed from {self._hvac_mode} to {new_hvac_mode}")
            self._hvac_mode = new_hvac_mode
        
        # Store the device status in hass.data to be reused by other entities
        self.hass.data[DOMAIN]["device_status"] = device_status
        
        self.async_write_ha_state()
