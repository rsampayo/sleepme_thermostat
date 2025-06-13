import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client

from .const import DEFAULT_API_URL, DOMAIN
from .sleepme import SleepMeClient

_LOGGER = logging.getLogger(__name__)


class SleepMeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SleepMe Thermostat."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.api_token = None
        self.devices = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self.api_token = user_input[CONF_API_TOKEN]
            try:
                client = SleepMeClient(aiohttp_client.async_get_clientsession(self.hass), DEFAULT_API_URL, self.api_token, None)
                all_devices = await client.get_all_devices()
                if not all_devices:
                    errors["base"] = "no_devices_found"
                else:
                    self.devices = {
                        dev["name"]: {
                            "device_id": dev["id"],
                            "firmware_version": dev.get("firmware_version", "N/A"),
                            "mac_address": dev.get("mac_address", "N/A"),
                            "model": dev.get("model", "N/A"),
                            "serial_number": dev.get("serial_number", "N/A"),
                            "display_name": dev.get("name", "SleepMe Device"),
                        }
                        for dev in all_devices
                    }
                    return await self.async_step_select_device()
            except Exception as e:
                _LOGGER.error("Failed to connect to SleepMe API: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
            errors=errors,
        )

    async def async_step_select_device(self, user_input=None):
        """Handle device selection."""
        if user_input is not None:
            device_name = user_input["device_name"]
            device_info = self.devices[device_name]
            device_id = device_info["device_id"]
            
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=device_name,
                data={
                    "api_url": DEFAULT_API_URL,
                    "api_token": self.api_token,
                    "device_id": device_id,
                    **device_info,
                },
            )

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {vol.Required("device_name"): vol.In(list(self.devices.keys()))}
            ),
        )