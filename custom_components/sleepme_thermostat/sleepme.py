import logging
from .sleepme_api import SleepMeAPI
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

def round_half_up(n):
    """Round a number to the nearest .0 or .5."""
    return round(n * 2) / 2

class SleepMeClient:
    def __init__(self, hass: HomeAssistant, api_url: str, token: str, device_id: str = None):
        self.api_url = api_url
        self.token = token
        self.device_id = device_id
        self.api = SleepMeAPI(hass, api_url, token)
        _LOGGER.debug(f"[Device {self.device_id}] Initialized SleepMeClient with API URL: {self.api_url}")

    async def set_temp_level(self, temp_c: float, retries: int = 2):
        """Set the temperature level in Celsius and provide feedback, with retry logic."""
        temp_c = round_half_up(temp_c)
        endpoint = f"devices/{self.device_id}"
        data = {"set_temperature_c": temp_c}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set temperature to {temp_c}C")

        response = await self.api.api_request("PATCH", endpoint, data=data, retries=retries)

        if not response:
            _LOGGER.warning(f"Failed to set temperature to {temp_c}C for device {self.device_id}. Received empty response.")
            return {}

        if response.get("set_temperature_c") == temp_c:
            _LOGGER.info(f"[Device {self.device_id}] Temperature successfully set to {temp_c}C.")

        return response

    async def set_device_status(self, status: str, retries: int = 2):
        """Set the device status to either 'active' (on) or 'standby' (off), with retry logic."""
        if status not in ["active", "standby"]:
            raise ValueError("Status must be either 'active' or 'standby'.")

        endpoint = f"devices/{self.device_id}"
        data = {"thermal_control_status": status}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set device status to {status}")

        response = await self.api.api_request("PATCH", endpoint, data=data, retries=retries)

        if not response:
            _LOGGER.warning(f"Failed to set device status to {status} for device {self.device_id}. Received empty response.")
            return {}

        if response.get("thermal_control_status") == status:
            _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status}.")

        return response

    async def get_claimed_devices(self, retries: int = 1):
        """Return a list of claimed devices for the given token, with retry logic."""
        endpoint = "devices"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching claimed devices from {endpoint}")
        
        response = await self.api.api_request("GET", endpoint, retries=retries)

        if isinstance(response, list):
            _LOGGER.info(f"Successfully fetched claimed devices: {response}")
            return response

        _LOGGER.error(f"Unexpected response format for claimed devices: {response}")
        return []

    async def get_device_status(self, retries: int = 0):
        """Retrieve the device status, with retry logic."""
        endpoint = f"devices/{self.device_id}"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching device status from {endpoint}")
        
        response = await self.api.api_request("GET", endpoint, retries=retries)
        
        if isinstance(response, dict):
            _LOGGER.debug(f"[Device {self.device_id}] Device status: {response}")
            return response
        
        _LOGGER.error(f"Failed to fetch device status for {self.device_id}. Response: {response}")
        return {}