"""DataUpdateCoordinator for SleepMe devices.

Translates transport-layer typed exceptions into HA framework exceptions:
- 401/403 (SleepMeAuthError) -> ConfigEntryAuthFailed (triggers reauth flow)
- transient/rate-limit/connection -> UpdateFailed (HA backs off polling)

No stale-data fallback: if a poll fails, HA's framework handles the entity
availability semantics (CoordinatorEntity flips to unavailable until the next
successful update).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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


async def _async_fetch[T](coro: Awaitable[T]) -> T:
    """Run a client request and translate transport failures for coordinators."""
    try:
        return await coro
    except SleepMeAuthError as err:
        raise ConfigEntryAuthFailed("Invalid or revoked SleepMe API token") from err
    except SleepMeRateLimited as err:
        raise UpdateFailed(
            "SleepMe API rate-limited; will retry next interval"
        ) from err
    except SleepMeConnectionError as err:
        raise UpdateFailed(f"Cannot reach SleepMe API: {err}") from err
    except httpx.HTTPStatusError as err:
        raise UpdateFailed(f"HTTP {err.response.status_code} from SleepMe API") from err
    except ValueError as err:
        raise UpdateFailed(str(err)) from err


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
        super().__init__(
            hass,
            _LOGGER,
            name=f"SleepMe Update Manager {device_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict:
        """Fetch the latest device status. Raise typed framework exceptions on failure."""
        device_status = await _async_fetch(self.client.get_device_status())

        return {
            "status": device_status.get("status", {}),
            "control": device_status.get("control", {}),
            "about": device_status.get("about", {}),
        }


class SleepReportUpdateManager(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch the account's seven-day sleep-report window at a gentle cadence."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        *,
        time_zone: str,
        days_back: int,
        scan_interval: int,
    ) -> None:
        self.client = SleepMeClient(hass, api_url, token)
        self.time_zone = time_zone
        self.days_back = days_back
        super().__init__(
            hass,
            _LOGGER,
            name="SleepMe Sleep Reports",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch reports through today in Home Assistant's configured zone."""
        return await _async_fetch(
            self.client.get_sleep_reports(
                start_date=datetime.now(ZoneInfo(self.time_zone)).date(),
                days_back=self.days_back,
                time_zone=self.time_zone,
            )
        )
