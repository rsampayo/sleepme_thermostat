import asyncio
import logging
from typing import Any, Awaitable, Callable

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    PRESET_NONE
)
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, PRESET_MAX_COOL, PRESET_MAX_HEAT, PRESET_TEMPERATURES

_LOGGER = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
POST_COMMAND_DELAY = 10
RETRY_DELAY = 127

def round_half_up(n):
    """Round a number to the nearest .0 or .5."""
    return round(n * 2) / 2

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
        self._previous_target_temperature = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._name,
            "manufacturer": "SleepMe",
            "model": device_info.get("model"),
            "sw_version": device_info.get("firmware_version"),
            "connections": {("mac", device_info.get("mac_address"))},
            "serial_number": device_info.get("serial_number"),
        }
    
    async def _async_api_command_with_retry(
        self,
        command_callable: Callable[[], Awaitable[Any]],
        verification_callable: Callable[[], bool],
        command_description: str,
    ) -> bool:
        """
        Execute an API command with a retry mechanism to handle rate limiting.
        Returns True on success, False on failure.
        """
        for attempt in range(RETRY_ATTEMPTS):
            _LOGGER.debug(
                "Executing command '%s', attempt %d of %d",
                command_description, attempt + 1, RETRY_ATTEMPTS
            )
            try:
                await command_callable()
            except Exception as e:
                _LOGGER.warning(
                    "API command '%s' failed on attempt %d: %s",
                    command_description, attempt + 1, e
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue

            await asyncio.sleep(POST_COMMAND_DELAY)

            await self.coordinator.async_request_refresh()

            if verification_callable():
                _LOGGER.info(
                    "Command '%s' successfully verified after attempt %d.",
                    command_description, attempt + 1
                )
                self.async_write_ha_state()
                return True

            _LOGGER.warning(
                "Verification for '%s' failed on attempt %d. State not updated.",
                command_description, attempt + 1
            )
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY)

        _LOGGER.error(
            "Failed to execute and verify command '%s' after %d attempts.",
            command_description, RETRY_ATTEMPTS
        )
        return False

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
    def preset_modes(self):
        return [PRESET_NONE, PRESET_MAX_HEAT, PRESET_MAX_COOL]

    @property
    def preset_mode(self):
        if self.hvac_mode == HVACMode.OFF:
            return PRESET_NONE
        return self._determine_preset_mode(self.coordinator.data["control"].get("set_temperature_c"))

    @property
    def supported_features(self):
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.TURN_OFF |
            ClimateEntityFeature.PRESET_MODE
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
        """Set new target temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            target_temp = kwargs.get("temperature")
            if target_temp is None:
                raise ValueError("Temperature is required")

        if (target_temp < self.min_temp or target_temp > self.max_temp) and \
           (target_temp not in PRESET_TEMPERATURES.values()):
            _LOGGER.warning(f"[Device {self._device_id}] Temperature {target_temp}C is out of range.")
            return

        _LOGGER.info(f"[Device {self._device_id}] Setting target temperature to {target_temp}C")
        
        command_func = lambda: self.coordinator.client.set_temp_level(target_temp)
        verification = lambda: self.coordinator.data["control"].get("set_temperature_c") == round_half_up(target_temp)

        await self._async_api_command_with_retry(
            command_callable=command_func,
            verification_callable=verification,
            command_description=f"Set temperature to {target_temp}C"
        )

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode not in [HVACMode.AUTO, HVACMode.OFF]:
            return

        target_status = "active" if hvac_mode == HVACMode.AUTO else "standby"

        command_func = lambda: self.coordinator.client.set_device_status(target_status)
        verification = lambda: self.coordinator.data["control"].get("thermal_control_status") == target_status

        await self._async_api_command_with_retry(
            command_callable=command_func,
            verification_callable=verification,
            command_description=f"Set HVAC mode to {hvac_mode}"
        )

    async def async_set_preset_mode(self, preset_mode):
        """Set new preset mode."""
        if self.hvac_mode == HVACMode.OFF and preset_mode != PRESET_NONE:
            await self.async_set_hvac_mode(HVACMode.AUTO)

        if preset_mode in PRESET_TEMPERATURES:
            if self.target_temperature is not None:
                self._previous_target_temperature = self.target_temperature
            await self.async_set_temperature(temperature=PRESET_TEMPERATURES[preset_mode])
        elif preset_mode == PRESET_NONE:
            if self.target_temperature is None:
                if self._previous_target_temperature is not None:
                    await self.async_set_temperature(temperature=self._previous_target_temperature)
                else:
                    await self.async_set_temperature(temperature=self.current_temperature)

    def _sanitize_temperature(self, temp):
        """Sanitize temperature values returned by the API."""
        if temp in PRESET_TEMPERATURES.values():
            return None
        return temp

    def _determine_hvac_mode(self, thermal_control_status):
        """Determine the HVAC mode based on the device's thermal control status."""
        if thermal_control_status == "active":
            return HVACMode.AUTO
        return HVACMode.OFF

    def _determine_preset_mode(self, target_temperature):
        """Determine the active preset mode, if any."""
        for (mode, target) in PRESET_TEMPERATURES.items():
            if target_temperature == target:
                return mode
        return PRESET_NONE