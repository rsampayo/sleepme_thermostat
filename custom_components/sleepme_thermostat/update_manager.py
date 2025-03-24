import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant
from datetime import timedelta
from .sleepme import SleepMeClient

_LOGGER = logging.getLogger(__name__)

class SleepMeUpdateManager(DataUpdateCoordinator):
    """Manages data updates for SleepMe devices."""

    def __init__(self, hass: HomeAssistant, api_url: str, token: str, device_id: str):
        self.client = SleepMeClient(hass, api_url, token, device_id)
        self.device_id = device_id

        # Initialize the last known good status as None
        self._last_valid_status = None

        # Set the update interval to 20 seconds
        update_interval = timedelta(seconds=20)

        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Update Manager {device_id}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch the latest data from the SleepMe API."""
        try:
            # Fetch device status from the API
            device_status = await self.client.get_device_status()

            # If the device status is empty, return the last valid status
            if not device_status:
                _LOGGER.warning(f"Using last valid status for device {self.device_id} due to empty or failed update.")
                return self._last_valid_status or {
                    "status": {},
                    "control": {},
                    "about": {},
                }

            # Cache the current valid status
            self._last_valid_status = {
                "status": device_status.get("status", {}),
                "control": device_status.get("control", {}),
                "about": device_status.get("about", {}),
            }

            return self._last_valid_status

        except Exception as e:
            _LOGGER.error(f"Error updating device data for {self.device_id}: {e}")
            # If an error occurs, return the last valid status
            return self._last_valid_status or {
                "status": {},
                "control": {},
                "about": {},
            }
