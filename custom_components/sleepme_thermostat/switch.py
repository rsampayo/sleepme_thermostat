import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, SCHEDULE_SWITCH_NAME
from .pysleepme import SleepMeClient
from .update_manager import SleepMeUpdateManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SleepMe switch entities."""
    device_id = config_entry.data.get("device_id")
    device_display_name = config_entry.data.get("device_display_name")
    update_manager = hass.data[DOMAIN][f"{device_id}_update_manager"]
    client = hass.data[DOMAIN]["sleepme_controller"]
    device_info_data = hass.data[DOMAIN]["device_info"]

    async_add_entities(
        [
            SleepMeScheduleSwitch(
                update_manager, client, device_id, device_display_name, device_info_data
            )
        ]
    )


class SleepMeScheduleSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a SleepMe schedule switch."""

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        client: SleepMeClient,
        device_id: str,
        device_display_name: str,
        device_info_data: dict,
    ):
        """Initialize the switch."""
        super().__init__(coordinator)
        self.client = client
        self._device_id = device_id
        self._attr_name = f"{device_display_name} {SCHEDULE_SWITCH_NAME}"
        self._attr_unique_id = f"{device_id}_schedule_switch"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": device_display_name,
            "manufacturer": MANUFACTURER,
            "model": device_info_data.get("model"),
            "sw_version": device_info_data.get("firmware_version"),
        }

    @property
    def is_on(self) -> bool:
        """Return true if the schedule is enabled."""
        control = self.coordinator.data.get("control", {})
        return control.get("has_schedule_enabled", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device schedule on."""
        if await self.client.set_schedule_enabled(True):
            control = self.coordinator.data.get("control", {})
            control["has_schedule_enabled"] = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device schedule off."""
        if await self.client.set_schedule_enabled(False):
            control = self.coordinator.data.get("control", {})
            control["has_schedule_enabled"] = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()