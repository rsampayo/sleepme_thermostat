"""DataUpdateCoordinator for SleepMe devices.

Translates transport-layer typed exceptions into HA framework exceptions:
- 401/403 (SleepMeAuthError) -> ConfigEntryAuthFailed (triggers reauth flow)
- transient/connection -> UpdateFailed (HA backs off polling)

If a poll fails, HA's framework handles the entity availability semantics
(CoordinatorEntity flips to unavailable until the next successful update).

One exception: a poll refused by our own rate limiter is not a failure of the
device or the API. The server was never asked. The coordinator keeps its last
data for up to MAX_CONSECUTIVE_SKIPPED_POLLS intervals instead of flapping
every entity to unavailable because a command used the last free slot.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .sleepme import SleepMeClient
from .sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
    SleepMeRateLimited,
)

_LOGGER = logging.getLogger(__name__)

# Beyond this many skipped polls in a row the data is too old to present as
# current, so the failure is surfaced.
MAX_CONSECUTIVE_SKIPPED_POLLS = 2


class SleepMeUpdateManager(DataUpdateCoordinator):
    """Manages data updates for a single SleepMe device."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        device_id: str,
        scan_interval: int = 20,
    ) -> None:
        self.client = SleepMeClient(hass, api_url, token, device_id)
        self.device_id = device_id
        self._consecutive_skipped_polls = 0
        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Update Manager {device_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict:
        """Fetch the latest device status. Raise typed framework exceptions on failure."""
        try:
            device_status = await self.client.get_device_status()
        except SleepMeAuthError as err:
            raise ConfigEntryAuthFailed("Invalid or revoked SleepMe API token") from err
        except SleepMeRateLimited as err:
            if (
                self.data is None
                or self._consecutive_skipped_polls >= MAX_CONSECUTIVE_SKIPPED_POLLS
            ):
                raise UpdateFailed(
                    "SleepMe API rate-limited; will retry next interval"
                ) from err
            self._consecutive_skipped_polls += 1
            _LOGGER.debug(
                "[Device %s] Poll skipped by the local rate limiter (%d in a row); "
                "keeping last data",
                self.device_id,
                self._consecutive_skipped_polls,
            )
            return self.data
        except SleepMeConnectionError as err:
            raise UpdateFailed(f"Cannot reach SleepMe API: {err}") from err
        except httpx.HTTPStatusError as err:
            # Non-401/403/429/5xx HTTP errors that transport let through.
            raise UpdateFailed(
                f"HTTP {err.response.status_code} from SleepMe API"
            ) from err
        except ValueError as err:
            raise UpdateFailed(str(err)) from err

        self._consecutive_skipped_polls = 0
        return {
            "status": device_status.get("status", {}),
            "control": device_status.get("control", {}),
            "about": device_status.get("about", {}),
        }
