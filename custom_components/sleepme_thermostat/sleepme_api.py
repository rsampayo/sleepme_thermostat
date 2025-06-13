import logging
import time
import httpx

_LOGGER = logging.getLogger(__name__)

class SleepMeAPI:
    """A low-level client for the SleepMe API."""

    def __init__(self, api_url, token, device_id):
        """Initialize the API client."""
        self.base_url = api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        self.device_id = device_id
        self.client = httpx.AsyncClient()

    async def get_all_devices(self):
        """Get a list of all devices from the API."""
        url = f"{self.base_url}/devices"
        try:
            response = await self.client.get(url, headers=self.headers)
            response.raise_for_status() 
            return response.json()
        except httpx.RequestError as e:
            _LOGGER.error(f"Error requesting all devices: {e}")
            return None

    async def get_device_status(self):
        """Get the status of a specific device."""
        if not self.device_id:
            return None
        url = f"{self.base_url}/devices/{self.device_id}"
        try:
            response = await self.client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            _LOGGER.error(f"Error requesting device status for {self.device_id}: {e}")
            return None

    async def patch_device_control(self, payload):
        """Send a PATCH request to control the device."""
        if not self.device_id:
            return None
        url = f"{self.base_url}/devices/{self.device_id}"
        try:
            response = await self.client.patch(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            _LOGGER.error(f"Error sending command to {self.device_id}: {e}")
            return None