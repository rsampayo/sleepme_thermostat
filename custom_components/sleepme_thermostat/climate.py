import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    HVAC_ACTION_COOLING,
    HVAC_ACTION_HEATING,
    HVAC_ACTION_IDLE,
    HVAC_ACTION_OFF,
    HVAC_MODES,
    MANUFACTURER,
    PRESET_PRECONDITIONING,
    SUPPORT_FLAGS,
)
from .sleepme import SleepMeClient
from .update_manager import SleepMeUpdateManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SleepMe climate entities."""
    device_id = config_entry.data.get("device_id")
    device_display_name = config_entry.data.get("display_name")
    update_manager = hass.data[DOMAIN][f"{device_id}_update_manager"]
    client = hass.data[DOMAIN]["sleepme_controller"]
    device_info_data = hass.data[DOMAIN]["device_info"]

    async_add_entities(
        [
            SleepMeClimateEntity(
                update_manager, client, device_id, device_display_name, device_info_data
            )
        ]
    )


class SleepMeClimateEntity(CoordinatorEntity, ClimateEntity):
    """Representation of a SleepMe climate entity."""

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        client: SleepMeClient,
        device_id: str,
        device_display_name: str,
        device_info_data: dict,
    ):
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self.client = client
        self._device_id = device_id
        
        self._attr_name = device_display_name
        self._attr_unique_id = f"{device_id}_climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = HVAC_MODES
        self._attr_supported_features = SUPPORT_FLAGS
        self._attr_preset_modes = [PRESET_PRECONDITIONING]

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._attr_name,
            "manufacturer": MANUFACTURER,
            "model": device_info_data.get("model"),
            "sw_version": device_info_data.get("firmware_version"),
        }

    @property
    def hvac_mode(self):
        """Return the current HVAC mode."""
        status = self.coordinator.data.get("status", {})
        thermal_status = status.get("thermal_control_status")

        if thermal_status in ["active", "preconditioning"]:
            set_temp = status.get("set_temperature_c")
            current_temp = status.get("current_temperature_c")
            if set_temp is not None and current_temp is not None:
                return HVACMode.COOL if set_temp < current_temp else HVACMode.HEAT
            return HVACMode.COOL
        return HVACMode.OFF

    @property
    def hvac_action(self):
        """Return the current HVAC action."""
        status = self.coordinator.data.get("status", {})
        thermal_status = status.get("thermal_control_status")

        if thermal_status in ["active", "preconditioning"]:
            set_temp = status.get("set_temperature_c")
            current_temp = status.get("current_temperature_c")
            if set_temp is not None and current_temp is not None:
                if set_temp < current_temp:
                    return HVAC_ACTION_COOLING
                if set_temp > current_temp:
                    return HVAC_ACTION_HEATING
                return HVAC_ACTION_IDLE
            return HVAC_ACTION_COOLING
        return HVAC_ACTION_OFF

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        status = self.coordinator.data.get("status", {})
        if status.get("thermal_control_status") == "preconditioning":
            return PRESET_PRECONDITIONING
        return None

    @property
    def current_temperature(self):
        """Return the current temperature."""
        status = self.coordinator.data.get("status", {})
        return status.get("current_temperature_c")

    @property
    def target_temperature(self):
        """Return the target temperature."""
        status = self.coordinator.data.get("status", {})
        return status.get("set_temperature_c")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temperature_c = kwargs.get(ATTR_TEMPERATURE)
        if temperature_c is None:
            return

        if await self.client.set_temperature(temperature_c):
            status = self.coordinator.data.get("status", {})
            status["set_temperature_c"] = temperature_c
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set a new HVAC mode."""
        is_active = hvac_mode in [HVACMode.COOL, HVACMode.HEAT]

        if await self.client.set_power_status(is_active):
            status = self.coordinator.data.get("status", {})
            status["thermal_control_status"] = "active" if is_active else "standby"
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()