import asyncio
import httpx
import logging
import time
from .const import *

_LOGGER = logging.getLogger(__name__)

# Global rate limit settings
MAX_REQUESTS_PER_MINUTE = 9
RATE_LIMIT_INTERVAL = 60  # seconds in one minute
last_request_times = []
rate_limit_lock = asyncio.Lock()

def round_half_up(n):
    """Round a number to the nearest .0 or .5."""
    return round(n * 2) / 2

class SleepMeClient:
    def __init__(self, api_url: str, token: str, device_id: str = None):
        self.api_url = api_url
        self.token = token
        self.device_id = device_id

    async def rate_limited_request(self, method: str, url: str, params=None, data=None, input_headers=None, retries=5):
        """Make an API request with global rate limiting and retry logic for 429 errors."""
        async with rate_limit_lock:
            global last_request_times
            current_time = time.time()

            # Remove timestamps older than one minute
            last_request_times = [t for t in last_request_times if current_time - t < RATE_LIMIT_INTERVAL]

            if len(last_request_times) >= MAX_REQUESTS_PER_MINUTE:
                wait_time = RATE_LIMIT_INTERVAL - (current_time - last_request_times[0])
                _LOGGER.debug(f"[Device {self.device_id}] Rate limiting: waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
                current_time = time.time()
                last_request_times = [t for t in last_request_times if current_time - t < RATE_LIMIT_INTERVAL]

            last_request_times.append(current_time)

            return await self.api_request(method, url, params, data, input_headers, retries)

    async def api_request(self, method: str, url: str, params=None, data=None, input_headers=None, retries=5):
        """Make an API request with retry logic for handling 429 errors."""
        headers = input_headers or DEFAULT_API_HEADERS.copy()
        headers["Authorization"] = f"Bearer {self.token}"

        for attempt in range(retries):
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=headers, json=data, params=params)
                if response.status_code == 429:
                    _LOGGER.warning(f"[Device {self.device_id}] 429 Too Many Requests. Attempt {attempt + 1} of {retries}. Retrying after delay...")
                    await asyncio.sleep((2 ** attempt) * 10)  # Exponential backoff starting at 10 seconds
                    continue
                response.raise_for_status()
                return response.json()

        _LOGGER.error(f"[Device {self.device_id}] API request failed after {retries} attempts.")
        return {}

    async def get_claimed_devices(self):
        """Return a list of claimed devices for the given token."""
        url = f"{self.api_url}/devices"
        return await self.rate_limited_request("GET", url)

    async def get_device_status(self):
        """Retrieve the device status."""
        url = f"{self.api_url}/devices/{self.device_id}"
        return await self.rate_limited_request("GET", url)

    async def set_temp_level(self, temp_c: float):
        """Set the temperature level in Celsius and provide feedback."""
        temp_c = round_half_up(temp_c)  # Round the temperature to the nearest .0 or .5
        url = f"{self.api_url}/devices/{self.device_id}"
        data = {"set_temperature_c": temp_c}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set temperature to {temp_c}C")
        
        # Send the request to set the temperature level
        response = await self.rate_limited_request("PATCH", url, data=data)
        
        # Check if the temperature setting was successful
        if response.get("set_temperature_c") == temp_c:
            _LOGGER.info(f"[Device {self.device_id}] Temperature successfully set to {temp_c}C.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Temperature setting may have failed. Response: {response}")
            
            # Explanation: The physical device may not respond fast enough, and the API might return stale data
            # that has not been updated yet. To handle this, we wait for a few seconds before rechecking.
            await asyncio.sleep(8)  # Wait for 6 seconds before re-checking the temperature setting
            
            # Re-check the temperature setting after the delay
            device_status = await self.get_device_status()
            actual_temp = device_status.get("control", {}).get("set_temperature_c")
            
            if actual_temp == temp_c:
                _LOGGER.info(f"[Device {self.device_id}] Temperature successfully set to {temp_c}C after re-check.")
            else:
                _LOGGER.warning(f"[Device {self.device_id}] Temperature still not set to {temp_c}C after re-check. Expected: {temp_c}, Actual: {actual_temp}")

    async def set_device_status(self, status: str):
        """Set the device status to either 'active' (on) or 'standby' (off)."""
        if status not in ["active", "standby"]:
            raise ValueError("Status must be either 'active' or 'standby'.")
        url = f"{self.api_url}/devices/{self.device_id}"
        data = {"thermal_control_status": status}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set device status to {status}")
        
        # Send the request to set the device status
        response = await self.rate_limited_request("PATCH", url, data=data)
        
        # Check if the status change was successful
        if response.get("thermal_control_status") == status:
            _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status}.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Device status may not have been set to {status}. Response: {response}")
            
            # Explanation: Similar to the temperature setting, the device might not update its status
            # immediately. We wait for a few seconds and recheck the status to ensure accuracy.
            await asyncio.sleep(8)  # Wait for 6 seconds before re-checking the device status
            
            # Re-check the device status after the delay
            device_status = await self.get_device_status()
            actual_status = device_status.get("control", {}).get("thermal_control_status")
            
            if actual_status == status:
                _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status} after re-check.")
            else:
                _LOGGER.warning(f"[Device {self.device_id}] Device status still not set to {status} after re-check. Expected: {status}, Actual: {actual_status}")

# Initialize the controller globally
sleepme_controller = None
