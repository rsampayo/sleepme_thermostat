import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant
from datetime import timedelta
from .sleepme import SleepMeClient

_LOGGER = logging.getLogger(__name__)

class SleepMeUpdateManager(DataUpdateCoordinator):
    """Manages data updates for SleepMe devices."""

    def __init__(self, hass: HomeAssistant, api_url: str, token: str, device_id: str):
        self.client = SleepMeClient(api_url, token, device_id)
        self.device_id = device_id

        # Set the update interval to 15 seconds
        update_interval = timedelta(seconds=30)

        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Update Manager {device_id}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch the latest data from the SleepMe API."""
        try:
            # Fetch both device status and "about" info
            device_status = await self.client.get_device_status()
            device_info = await self.client.get_device_info()

            # Combine them into one dictionary for easier access
            return {
                "status": device_status.get("status", {}),
                "control": device_status.get("control", {}),
                "about": device_info,
            }

        except Exception as e:
            _LOGGER.error(f"Error updating device data for {self.device_id}: {e}")
            raise
