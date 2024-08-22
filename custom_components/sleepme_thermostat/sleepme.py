import logging
from .sleepme_api import SleepMeAPI

_LOGGER = logging.getLogger(__name__)

def round_half_up(n):
    """Round a number to the nearest .0 or .5."""
    return round(n * 2) / 2

class SleepMeClient:
    def __init__(self, api_url: str, token: str, device_id: str = None):
        self.api_url = api_url
        self.token = token
        self.device_id = device_id
        self.api = SleepMeAPI(api_url, token)
        _LOGGER.debug(f"[Device {self.device_id}] Initialized SleepMeClient with API URL: {self.api_url}")

    async def set_temp_level(self, temp_c: float):
        """Set the temperature level in Celsius and provide feedback."""
        temp_c = round_half_up(temp_c)
        endpoint = f"devices/{self.device_id}"
        data = {"set_temperature_c": temp_c}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set temperature to {temp_c}C")

        response = await self.api.make_request("PATCH", endpoint, data=data)

        # Handle the response, knowing it's always a dictionary
        if not response:
            _LOGGER.warning(f"Failed to set temperature to {temp_c}C for device {self.device_id}. Received empty response.")
            return {}

        # Log the successful response
        if response.get("set_temperature_c") == temp_c:
            _LOGGER.info(f"[Device {self.device_id}] Temperature successfully set to {temp_c}C.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Temperature may not have been set to {temp_c}C. Response: {response}")

        return response

    async def set_device_status(self, status: str):
        """Set the device status to either 'active' (on) or 'standby' (off)."""
        if status not in ["active", "standby"]:
            raise ValueError("Status must be either 'active' or 'standby'.")

        endpoint = f"devices/{self.device_id}"
        data = {"thermal_control_status": status}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set device status to {status}")

        response = await self.api.make_request("PATCH", endpoint, data=data)

        # Handle the response, knowing it's always a dictionary
        if not response:
            _LOGGER.warning(f"Failed to set device status to {status} for device {self.device_id}. Received empty response.")
            return {}

        # Log the successful response
        if response.get("thermal_control_status") == status:
            _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status}.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Device status may not have been set to {status}. Response: {response}")

        return response

    async def get_claimed_devices(self):
        """Return a list of claimed devices for the given token."""
        endpoint = "devices"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching claimed devices from {endpoint}")
        
        response = await self.api.make_request("GET", endpoint)

        # Log an error if no devices are returned
        if not response or not response.get('devices'):
            _LOGGER.error(f"No devices found for the given token at {endpoint}. Response: {response}")
            return []

        _LOGGER.info(f"Successfully fetched claimed devices for {self.device_id}.")
        return response

    async def get_device_status(self):
        """Retrieve the device status."""
        endpoint = f"devices/{self.device_id}"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching device status from {endpoint}")
        response = await self.api.make_request("GET", endpoint)
        _LOGGER.debug(f"[Device {self.device_id}] Device status: {response}")
        return response
