# custom_components/sleepme_thermostat/update_manager.py

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .pysleepme import SleepMeClient, SleepMeClientError

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL_SECONDS = 20

class SleepMeUpdateManager(DataUpdateCoordinator):
    """Manages data updates and communication with the SleepMe API."""

    def __init__(self, hass: HomeAssistant, client: SleepMeClient):
        """Initialize the update manager."""
        self.client = client

        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Dock Pro {client.device_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch the latest data from the SleepMe API.

        This method is called by the DataUpdateCoordinator to refresh the data.
        If it fails, it raises UpdateFailed to notify Home Assistant.
        """
        try:
            device_status = await self.client.get_device_status()

            if not device_status:
                _LOGGER.debug(
                    "Failed to update device %s: API returned an empty response",
                    self.client.device_id,
                )
                raise UpdateFailed("API returned an empty response.")

            return {
                "status": device_status.get("status", {}),
                "control": device_status.get("control", {}),
                "about": device_status.get("about", {}),
            }

        except SleepMeClientError as err:
            _LOGGER.warning(
                "Failed to update device %s: %s", self.client.device_id, err
            )
            raise UpdateFailed(f"Error communicating with SleepMe API: {err}") from err
            
        except Exception as err:
            _LOGGER.error(
                "An unexpected error occurred while updating device %s: %s",
                self.client.device_id,
                err,
            )
            raise UpdateFailed(f"An unexpected error occurred: {err}") from err
