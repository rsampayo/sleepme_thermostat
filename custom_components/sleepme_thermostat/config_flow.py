import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from .sleepme import SleepMeClient
from .const import DOMAIN, API_URL
from httpx import HTTPStatusError

_LOGGER = logging.getLogger(__name__)

class SleepMeThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SleepMe Thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.api_token = ""

    @property
    def schema(self):
        """Return the schema for the current step."""
        return vol.Schema({
            vol.Required("api_token", default=""): str,
        })

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            _LOGGER.debug(f"User input received: {user_input}")
            self.api_token = user_input.get("api_token")

            # Instantiate SleepMeClient to get the list of devices
            client = SleepMeClient(API_URL, self.api_token)

            try:
                # Get the list of claimed devices
                claimed_devices = await client.get_claimed_devices()
                _LOGGER.debug(f"Claimed devices: {claimed_devices}")

                if not claimed_devices:
                    errors["base"] = "no_devices_found"
                else:
                    # Store the API token and claimed devices in the context
                    self.context["api_token"] = self.api_token
                    self.context["claimed_devices"] = claimed_devices
                    return await self.async_step_select_device()

            except HTTPStatusError as e:
                _LOGGER.error(f"HTTP error fetching claimed devices: {e}")
                # Check if the error is related to a 403 Forbidden response
                if e.response.status_code == 403:
                    errors["base"] = "invalid_token"
                else:
                    errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error(f"Unexpected error fetching claimed devices: {e}")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self.schema,
            errors=errors,
        )

    async def async_step_select_device(self, user_input=None) -> FlowResult:
        """Step 2: Select a device from the list of claimed devices."""
        errors = {}

        if user_input is not None:
            _LOGGER.debug(f"Device selected: {user_input}")

            # Retrieve the selected device name and ID
            device_id = user_input["device_id"]
            name = self.context["claimed_devices_dict"][device_id]

            # Set a unique ID for the device configuration
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            # Instantiate SleepMeClient to fetch device details
            client = SleepMeClient(API_URL, self.context["api_token"], device_id)

            try:
                # Fetch the "about" information for the selected device
                device_info = await client.get_device_info()
                _LOGGER.debug(f"Device info: {device_info}")

                # Store device info in the entry data
                return self.async_create_entry(
                    title=f"Dock Pro {name}",
                    data={
                        "api_url": API_URL,
                        "api_token": self.context["api_token"],
                        "device_id": device_id,
                        "name": name,
                        "firmware_version": device_info.get("firmware_version"),
                        "mac_address": device_info.get("mac_address"),
                        "model": device_info.get("model"),
                        "serial_number": device_info.get("serial_number"),
                    },
                )

            except Exception as e:
                _LOGGER.error(f"Error fetching device info: {e}")
                errors["base"] = "cannot_fetch_device_info"

        # Extract claimed devices from the previous step
        claimed_devices = self.context["claimed_devices"]
        claimed_devices_dict = {device["id"]: device["name"] for device in claimed_devices}
        self.context["claimed_devices_dict"] = claimed_devices_dict

        data_schema = vol.Schema({
            vol.Required("device_id"): vol.In(claimed_devices_dict)
        })

        return self.async_show_form(
            step_id="select_device",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_import(self, user_input=None) -> FlowResult:
        """Handle import from YAML."""
        return await self.async_step_user(user_input)