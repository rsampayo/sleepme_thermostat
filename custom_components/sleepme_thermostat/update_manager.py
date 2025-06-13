import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant
from datetime import timedelta
from .sleepme import SleepMeClient

_LOGGER = logging.getLogger(__name__)

class SleepMeUpdateManager(DataUpdateCoordinator):
    """Manages data updates for SleepMe devices."""

    def __init__(self, hass: HomeAssistant, client: SleepMeClient):
        """Initialize the update manager."""
        self.client = client
        self.device_id = client.device_id

        # Set the update interval to 60 seconds
        update_interval = timedelta(seconds=60)

        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Update Manager {self.device_id}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch the latest data from the SleepMe API."""
        try:
            device_status = await self.client.get_device_status()
            if not device_status:
                raise UpdateFailed("API returned an empty response.")

            return {
                "status": device_status.get("status", {}),
                "control": device_status.get("control", {}),
                "about": device_status.get("about", {}),
            }
        except Exception as e:
            raise UpdateFailed(f"Error updating device data for {self.device_id}: {e}") from e