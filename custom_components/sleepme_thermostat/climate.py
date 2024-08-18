import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from .sleepme import SleepMeClient
from .const import DOMAIN, API_URL
import asyncio
import time

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SleepMe Thermostat climate entity from a config entry."""
    device_id = entry.data.get("device_id")
    name = entry.data.get("name")

    _LOGGER.debug(f"[Device {device_id}] Setting up SleepMeThermostat entity with name: {name}")
    sleepme_controller = SleepMeClient(API_URL, entry.data.get("api_token"), device_id)
    thermostat = SleepMeThermostat(sleepme_controller, device_id, name, entry.data)
    
    hass.data[DOMAIN][device_id] = thermostat
    async_add_entities([thermostat])

class SleepMeThermostat(ClimateEntity):
    def __init__(self, controller, device_id, name, device_info):
        self._controller = controller
        self._name = f"Dock Pro {name}"
        self._device_id = device_id
        self._target_temperature = None
        self._hvac_mode = HVACMode.OFF
        self._supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.TURN_OFF
        )
        self._current_temperature = None
        self._is_water_low = False
        self._is_connected = False  # Add connection status attribute
        self._skip_next_update = False  # Flag to control whether to skip the next update
        self._attr_unique_id = f"{DOMAIN}_{device_id}_thermostat"

        # Store device info from the config entry
        self._firmware_version = device_info.get("firmware_version")
        self._mac_address = device_info.get("mac_address")
        self._model = device_info.get("model")
        self._serial_number = device_info.get("serial_number")

        # Validate MAC address
        if self._mac_address and len(self._mac_address) == 17 and self._mac_address.count(":") == 5:
            connections = {("mac", self._mac_address)}
        else:
            _LOGGER.warning(f"Invalid or missing MAC address for device {device_id}. Skipping MAC address in device registry.")
            connections = set()

        # Set up the device info attribute
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._name,
            "manufacturer": "SleepMe",
            "model": self._model,
            "sw_version": self._firmware_version,
            "connections": connections,
            "serial_number": self._serial_number,
        }

        self._last_update = 0  # Initialize the timestamp for the last update
        self._debounce_time = 5  # Set a debounce time in seconds
        _LOGGER.debug(f"[Device {self._device_id}] Initialized SleepMeThermostat entity")
        
        # Trigger an update as soon as the device is created
        asyncio.create_task(self.async_update())

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
            "is_connected": self._is_connected,  # Add connection status to state attributes
        }

#    @property
#    def is_connected(self):
#        """Return the connection status of the device."""
#        return self._is_connected

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
                _LOGGER.warning(f"[Device {self._device_id}] Temperature {target_temp}C is out of range. Must be between {self.min_temp}C and {self.max_temp}C.")
                return
            self._target_temperature = target_temp
            _LOGGER.info(f"[Device {self._device_id}] Set target temperature to {self._target_temperature}")
            await self._controller.set_temp_level(self._target_temperature)
            
            # Set flag to skip the next update since the state is already known
            self._skip_next_update = True

    async def async_set_hvac_mode(self, hvac_mode):
        self._hvac_mode = hvac_mode
        _LOGGER.info(f"[Device {self._device_id}] Set HVAC mode to {self._hvac_mode}")
        if hvac_mode == HVACMode.AUTO:
            await self._controller.set_device_status("active")
        elif hvac_mode == HVACMode.OFF:
            await self._controller.set_device_status("standby")

        # Set flag to skip the next update since the state is already known
        self._skip_next_update = True

    async def async_update(self):
        if self._skip_next_update:
            _LOGGER.debug(f"[Device {self._device_id}] Skipping the update as per the debounce mechanism.")
            self._skip_next_update = False  # Reset the flag after skipping the update
            return

        current_time = time.time()
        time_since_last_update = current_time - self._last_update

        if time_since_last_update < self._debounce_time:
            _LOGGER.debug(f"[Device {self._device_id}] Debounced update: Only {time_since_last_update:.2f} seconds since last update.")
            return

        self._last_update = current_time
        _LOGGER.debug(f"[Device {self._device_id}] Fetching device status from API")

        try:
            # Fetch the device status
            device_status = await self._controller.get_device_status()
            _LOGGER.debug(f"[Device {self._device_id}] Device status response: {device_status}")

            current_temp = self._sanitize_temperature(device_status.get("status", {}).get("water_temperature_c"))
            set_temp = self._sanitize_temperature(device_status.get("control", {}).get("set_temperature_c"))

            self._current_temperature = current_temp
            self._target_temperature = set_temp
            self._is_water_low = device_status.get("status", {}).get("is_water_low", False)
            self._is_connected = device_status.get("status", {}).get("is_connected", False)  # Update connection status

            self._hvac_mode = self._determine_hvac_mode(device_status.get("control", {}).get("thermal_control_status"))

            # Update the device info
            device_info = await self._controller.get_device_info()
            _LOGGER.debug(f"[Device {self._device_id}] Device info response: {device_info}")

            self._attr_device_info.update({
                "sw_version": device_info.get("firmware_version", self._firmware_version),
                "connections": {("mac", device_info.get("mac_address", self._mac_address))},
                "model": device_info.get("model", self._model),
                "serial_number": device_info.get("serial_number", self._serial_number),
            })

            # Store the device status in hass.data to be reused by other entities
            self.hass.data[DOMAIN]["device_status"] = device_status

            _LOGGER.debug(f"[Device {self._device_id}] Writing state to Home Assistant: current_temp={self._current_temperature}, target_temp={self._target_temperature}, hvac_mode={self._hvac_mode}, is_water_low={self._is_water_low}, is_connected={self._is_connected}")
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"[Device {self._device_id}] Error updating device status: {e}")

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
