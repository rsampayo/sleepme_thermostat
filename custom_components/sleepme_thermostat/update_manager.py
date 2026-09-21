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
from datetime import date, timedelta
from typing import Any

import httpx
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import MAX_SLEEP_REPORT_DAYS_BACK, SLEEP_REPORT_BACKFILL_INTERVAL
from .sleep_reports import (
    latest_sleep_report,
    summarize_sleep_history,
    summarize_sleep_report,
)
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
    """Keep a rolling month of account sleep reports.

    Every tick refreshes the newest seven-day window, because only recent
    reports can still change. Older windows are immutable, so each one is
    fetched once and cached. They are backfilled one per tick on a short
    interval, which keeps this coordinator at two requests per tick while it
    catches up and one request per tick afterwards.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        *,
        history_days: int,
        scan_interval: int,
        sleep_target_seconds: float,
    ) -> None:
        self.client = SleepMeClient(hass, api_url, token)
        self.history_days = history_days
        self.sleep_target_seconds = sleep_target_seconds
        # Derived once per refresh. 53 sensors read these; recomputing them in
        # every native_value was about 845 aggregation passes per refresh.
        self.latest_summary: dict[str, Any] = {}
        self.history_summary: dict[str, Any] = {}
        self._steady_interval = timedelta(seconds=scan_interval)
        self._backfill_interval = timedelta(seconds=SLEEP_REPORT_BACKFILL_INTERVAL)
        self._reports_by_date: dict[date, dict[str, Any]] = {}
        # None until the first tick decides which older windows are owed.
        self._pending_backfill: list[tuple[date, int]] | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="SleepMe Sleep Reports",
            update_interval=self._backfill_interval,
            # Reports change about once a day. Skip the state writes when a
            # refresh returns the same data.
            always_update=False,
        )

    @property
    def pending_backfill_windows(self) -> int:
        """Return how many older history windows are still to be fetched."""
        return len(self._pending_backfill or [])

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Refresh the newest window and backfill at most one older window."""
        # dt_util.now() uses HA's configured zone, which HA loads off the event
        # loop at startup. Building a ZoneInfo here would read tzdata from disk
        # inside the loop, and would also miss a later time-zone change.
        time_zone = self.hass.config.time_zone
        today = dt_util.now().date()
        newest_window, *older_windows = _report_windows(today, self.history_days)
        if self._pending_backfill is None:
            self._pending_backfill = older_windows

        # The newest window decides whether this refresh succeeded.
        newest_reports = await self._async_fetch_window(newest_window, time_zone)
        self._merge(newest_reports, overwrite=True)

        if self._pending_backfill:
            await self._async_backfill_one_window(time_zone)

        self.update_interval = (
            self._backfill_interval if self._pending_backfill else self._steady_interval
        )
        self._evict_older_than(today - timedelta(days=self.history_days - 1))
        reports = [self._reports_by_date[key] for key in sorted(self._reports_by_date)]
        self.latest_summary = summarize_sleep_report(
            latest_sleep_report(reports),
            sleep_target_seconds=self.sleep_target_seconds,
        )
        self.history_summary = summarize_sleep_history(
            reports,
            sleep_target_seconds=self.sleep_target_seconds,
            today=today,
        )
        return reports

    async def _async_backfill_one_window(self, time_zone: str) -> None:
        """Fetch the next owed history window; a failure only postpones it.

        Authentication failures are not caught here, so they still reach the
        reauth flow.
        """
        assert self._pending_backfill
        window = self._pending_backfill[0]
        try:
            reports = await self._async_fetch_window(window, time_zone)
        except UpdateFailed as err:
            _LOGGER.debug(
                "Sleep report history window ending %s not fetched; will retry: %s",
                window[0],
                err,
            )
            return
        # A fresher copy from the newest window wins over a backfilled one.
        self._merge(reports, overwrite=False)
        self._pending_backfill.pop(0)

    async def _async_fetch_window(
        self, window: tuple[date, int], time_zone: str
    ) -> list[dict[str, Any]]:
        window_end, days_back = window
        return await _async_fetch(
            self.client.get_sleep_reports(
                start_date=window_end,
                days_back=days_back,
                time_zone=time_zone,
            )
        )

    def _merge(self, reports: list[dict[str, Any]], *, overwrite: bool) -> None:
        """Cache reports by calendar date, ignoring ones without a valid date."""
        for report in reports:
            report_date = _parse_report_date(report.get("date"))
            if report_date is None:
                continue
            if overwrite or report_date not in self._reports_by_date:
                self._reports_by_date[report_date] = report

    def _evict_older_than(self, cutoff: date) -> None:
        """Drop cached dates that fell out of the history range."""
        for report_date in [key for key in self._reports_by_date if key < cutoff]:
            del self._reports_by_date[report_date]


def _parse_report_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _report_windows(end_date: date, history_days: int) -> list[tuple[date, int]]:
    """Split a history range into the endpoint's inclusive seven-day windows."""
    windows: list[tuple[date, int]] = []
    remaining = max(history_days, 1)
    window_end = end_date
    max_window_days = MAX_SLEEP_REPORT_DAYS_BACK + 1

    while remaining:
        window_days = min(remaining, max_window_days)
        windows.append((window_end, window_days - 1))
        remaining -= window_days
        window_end -= timedelta(days=window_days)

    return windows
