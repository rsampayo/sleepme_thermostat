import asyncio
import httpx
import logging
import time
from .const import *

_LOGGER = logging.getLogger(__name__)

# Global rate limit settings
MAX_REQUESTS_PER_MINUTE = 9
RATE_LIMIT_INTERVAL = 60  # seconds
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
        _LOGGER.debug(f"[Device {self.device_id}] Initialized SleepMeClient with API URL: {self.api_url}")

    async def rate_limited_request(self, method: str, url: str, params=None, data=None, input_headers=None, retries=5):
        """Make an API request with global rate limiting and retry logic for PATCH calls."""
        async with rate_limit_lock:
            current_time = time.time()

            # Remove timestamps older than RATE_LIMIT_INTERVAL
            self._clean_up_old_requests(current_time)

            if len(last_request_times) >= MAX_REQUESTS_PER_MINUTE:
                wait_time = RATE_LIMIT_INTERVAL - (current_time - last_request_times[0])
                _LOGGER.debug(f"[Device {self.device_id}] Rate limiting: waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
                current_time = time.time()
                self._clean_up_old_requests(current_time)

            last_request_times.append(current_time)
            _LOGGER.debug(f"[Device {self.device_id}] Making {method.upper()} request to {url} with params: {params}, data: {data}, and headers: {input_headers}")

            response = await self._perform_request(method, url, params, data, input_headers, retries if method == "PATCH" else 1)
            return response

    def _clean_up_old_requests(self, current_time):
        global last_request_times
        last_request_times = [t for t in last_request_times if current_time - t < RATE_LIMIT_INTERVAL]

    async def _perform_request(self, method: str, url: str, params=None, data=None, input_headers=None, retries=1):
        """Internal method to perform API requests with optional retry logic."""
        headers = input_headers or DEFAULT_API_HEADERS.copy()
        headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    _LOGGER.debug(f"[Device {self.device_id}] Attempt {attempt + 1} of {retries} for {method.upper()} request to {url}")
                    response = await client.request(method, url, headers=headers, json=data, params=params)
                    _LOGGER.debug(f"[Device {self.device_id}] Response received: {response.status_code}, Content: {response.text[:100]}...")

                    if response.status_code == 429:
                        if method == "PATCH":
                            backoff_time = (2 ** attempt) * 10
                            _LOGGER.warning(f"[Device {self.device_id}] 429 Too Many Requests. Retrying after {backoff_time} seconds...")
                            await asyncio.sleep(backoff_time)  # Exponential backoff starting at 10 seconds
                            continue
                    response.raise_for_status()
                    return self._process_response(response)

                except httpx.RequestError as e:
                    _LOGGER.error(f"[Device {self.device_id}] Request error: {str(e)}")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 403:
                        _LOGGER.error(f"[Device {self.device_id}] 403 Forbidden: Invalid API token.")
                        raise
                    _LOGGER.error(f"[Device {self.device_id}] HTTP error: {str(e)}")
                if method != "PATCH":
                    break  # Exit retry loop if not a PATCH request
                await asyncio.sleep((2 ** attempt) * 10)  # Exponential backoff

        _LOGGER.error(f"[Device {self.device_id}] API request failed after {retries} attempts.")
        return {}

    def _process_response(self, response):
        """Process the response, attempting to parse JSON."""
        try:
            response_json = response.json()
            _LOGGER.debug(f"[Device {self.device_id}] API request successful: {response_json}")
            return response_json
        except ValueError:
            _LOGGER.error(f"[Device {self.device_id}] Failed to decode JSON response: {response.text}")
            return response.text  # Handle non-JSON responses appropriately

    async def get_claimed_devices(self):
        """Return a list of claimed devices for the given token."""
        url = f"{self.api_url}/devices"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching claimed devices from {url}")
        return await self.rate_limited_request("GET", url)

    async def get_device_status(self):
        """Retrieve the device status."""
        url = f"{self.api_url}/devices/{self.device_id}"
        _LOGGER.debug(f"[Device {self.device_id}] Fetching device status from {url}")
        response = await self.rate_limited_request("GET", url)
        _LOGGER.debug(f"[Device {self.device_id}] Device status: {response}")
        return response

    async def get_device_info(self):
        """Fetch the about information for the device."""
        if not self.device_id:
            raise ValueError("Device ID must be set to get device info.")
            
        url = f"{self.api_url}/devices/{self.device_id}"
        headers = {'Authorization': f'Bearer {self.token}'}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data.get("about", {})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _LOGGER.warning(f"[Device {self.device_id}] 429 Too Many Requests: {str(e)}. Skipping this update cycle.")
                return {}
            raise

    async def set_temp_level(self, temp_c: float):
        """Set the temperature level in Celsius and provide feedback."""
        temp_c = round_half_up(temp_c)
        url = f"{self.api_url}/devices/{self.device_id}"
        data = {"set_temperature_c": temp_c}
        _LOGGER.debug(f"[Device {self.device_id}] Sending request to set temperature to {temp_c}C")

        response = await self.rate_limited_request("PATCH", url, data=data)

        if response.get("set_temperature_c") == temp_c:
            _LOGGER.info(f"[Device {self.device_id}] Temperature successfully set to {temp_c}C.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Temperature setting may have failed. Response: {response}")
            await asyncio.sleep(8)
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

        response = await self.rate_limited_request("PATCH", url, data=data)

        if response.get("thermal_control_status") == status:
            _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status}.")
        else:
            _LOGGER.warning(f"[Device {self.device_id}] Device status may not have been set to {status}. Response: {response}")
            await asyncio.sleep(8)
            device_status = await self.get_device_status()
            actual_status = device_status.get("control", {}).get("thermal_control_status")
            if actual_status == status:
                _LOGGER.info(f"[Device {self.device_id}] Device status successfully set to {status} after re-check.")
            else:
                _LOGGER.warning(f"[Device {self.device_id}] Device status still not set to {status} after re-check. Expected: {status}, Actual: {actual_status}")

# Initialize the controller globally
sleepme_controller = None
