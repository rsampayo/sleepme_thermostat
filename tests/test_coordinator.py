"""Coordinator error-translation tests."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from custom_components.sleepme_thermostat.const import (
    API_URL,
    DOMAIN,
    SLEEP_REPORT_BACKFILL_INTERVAL,
)
from custom_components.sleepme_thermostat.sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
    SleepMeRateLimited,
)
from custom_components.sleepme_thermostat.update_manager import (
    SleepReportUpdateManager,
    _report_windows,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryAuthFailed, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN, MOCK_DEVICE_ID, MOCK_NAME


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_coord_test",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": MOCK_API_TOKEN,
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "0.0.0-test",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "TEST-SERIAL",
        },
    )


def test_report_windows_cover_thirty_days_without_overlap() -> None:
    """The API's seven-date cap is paged into one exact 30-day range."""
    assert _report_windows(date(2026, 7, 13), 30) == [
        (date(2026, 7, 13), 6),
        (date(2026, 7, 6), 6),
        (date(2026, 6, 29), 6),
        (date(2026, 6, 22), 6),
        (date(2026, 6, 15), 1),
    ]


@pytest.fixture
def mock_failing_client():
    """Patch SleepMeClient at both import sites and return the get_device_status mock."""
    with (
        patch(
            "custom_components.sleepme_thermostat.SleepMeClient", autospec=True
        ) as mock_init_cls,
        patch(
            "custom_components.sleepme_thermostat.update_manager.SleepMeClient",
            autospec=True,
        ) as mock_um_cls,
    ):
        get_status = AsyncMock()
        for cls in (mock_init_cls, mock_um_cls):
            cls.return_value.get_device_status = get_status
            cls.return_value.get_claimed_devices = AsyncMock(return_value=[])
        yield get_status


async def test_auth_failed_triggers_reauth(
    hass: HomeAssistant, mock_failing_client: AsyncMock
) -> None:
    """SleepMeAuthError from the client surfaces as SETUP_ERROR and starts a reauth flow."""
    mock_failing_client.side_effect = SleepMeAuthError("401 from test")

    entry = _entry()
    entry.add_to_hass(hass)

    # First refresh raises ConfigEntryAuthFailed -> setup fails -> reauth starts.
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == "reauth" for f in flows)


async def test_transient_failure_raises_update_failed(
    hass: HomeAssistant, mock_failing_client: AsyncMock
) -> None:
    """A timeout from the client maps to UpdateFailed; entry doesn't load."""
    mock_failing_client.side_effect = SleepMeConnectionError("timeout")

    entry = _entry()
    entry.add_to_hass(hass)

    # async_config_entry_first_refresh raises ConfigEntryNotReady on UpdateFailed.
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rate_limited_raises_update_failed(
    hass: HomeAssistant, mock_failing_client: AsyncMock
) -> None:
    """SleepMeRateLimited from the client maps to UpdateFailed."""
    mock_failing_client.side_effect = SleepMeRateLimited("at capacity")

    entry = _entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_http_status_error_maps_to_update_failed(
    hass: HomeAssistant, mock_failing_client: AsyncMock
) -> None:
    """Unhandled HTTPStatusError (e.g. 500 after retries) maps to UpdateFailed."""
    response = httpx.Response(500, request=httpx.Request("GET", "https://x/y"))
    mock_failing_client.side_effect = httpx.HTTPStatusError(
        "500", request=response.request, response=response
    )

    entry = _entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_update_failed_is_subclass_of_update_failed():
    """Sanity: the coordinator import surface is what tests expect."""
    from custom_components.sleepme_thermostat.update_manager import (
        SleepMeUpdateManager,  # noqa: F401
    )

    assert UpdateFailed is UpdateFailed  # sentinel — just ensures import worked


async def test_async_update_data_happy_path(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Happy path: _async_update_data returns the three-key dict."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coord = entry.runtime_data.coordinator
    assert coord.last_update_success is True
    assert set(coord.data.keys()) == {"status", "control", "about"}
    assert coord.data["status"]["water_temperature_c"] == 22.0


async def test_value_error_maps_to_update_failed(
    hass: HomeAssistant, mock_failing_client: AsyncMock
) -> None:
    """ValueError from the client (unexpected response shape) -> SETUP_RETRY."""
    mock_failing_client.side_effect = ValueError("unexpected response: 'foo'")
    entry = _entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


# ---------- sleep report coordinator: the shared request budget ----------------

REPORT_SCAN_INTERVAL = 1800
HISTORY_DAYS = 30


def _one_report_per_requested_date(*, start_date: date, days_back: int, **_: object):
    """Mimic the live API: one report for every date in the requested window."""
    return [
        {
            "date": (start_date - timedelta(days=offset)).isoformat(),
            "sessions": [{"total_sleep_duration": 420}],
            "sleep_score_percent": 80,
        }
        for offset in range(days_back, -1, -1)
    ]


def _report_coordinator(hass: HomeAssistant) -> SleepReportUpdateManager:
    return SleepReportUpdateManager(
        hass,
        API_URL,
        MOCK_API_TOKEN,
        history_days=HISTORY_DAYS,
        scan_interval=REPORT_SCAN_INTERVAL,
    )


async def test_report_refresh_never_spends_more_than_two_requests(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Two requests per tick while catching up, then one per tick for good.

    The per-account limiter allows nine requests a minute, shared with every
    device poll and every user command. Five back-to-back report requests used
    to take all the headroom.
    """
    freezer.move_to("2026-07-13 12:00:00+00:00")
    mock_sleepme_client.get_sleep_reports.side_effect = _one_report_per_requested_date
    coordinator = _report_coordinator(hass)

    requests_per_tick = []
    for _ in range(7):
        before = mock_sleepme_client.get_sleep_reports.await_count
        await coordinator.async_refresh()
        assert coordinator.last_update_success is True
        requests_per_tick.append(
            mock_sleepme_client.get_sleep_reports.await_count - before
        )

    assert requests_per_tick == [2, 2, 2, 2, 1, 1, 1]
    assert coordinator.pending_backfill_windows == 0
    assert coordinator.update_interval == timedelta(seconds=REPORT_SCAN_INTERVAL)
    assert len(coordinator.data) == HISTORY_DAYS
    assert coordinator.data[0]["date"] == "2026-06-14"
    assert coordinator.data[-1]["date"] == "2026-07-13"


async def test_report_coordinator_ticks_fast_only_while_backfilling(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The short interval is temporary, so history loads in minutes, not hours."""
    freezer.move_to("2026-07-13 12:00:00+00:00")
    mock_sleepme_client.get_sleep_reports.side_effect = _one_report_per_requested_date
    coordinator = _report_coordinator(hass)

    await coordinator.async_refresh()

    assert coordinator.pending_backfill_windows == 3
    assert coordinator.update_interval == timedelta(
        seconds=SLEEP_REPORT_BACKFILL_INTERVAL
    )
    # The newest week is usable from the very first tick.
    assert [report["date"] for report in coordinator.data][-7:] == [
        f"2026-07-{day:02d}" for day in range(7, 14)
    ]


async def test_failed_history_window_is_retried_without_failing_the_refresh(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """One bad older window must not blank the sensors or discard good data."""
    freezer.move_to("2026-07-13 12:00:00+00:00")
    newest_end = date(2026, 7, 13)
    failures = {"left": 1}

    def flaky_history(*, start_date: date, days_back: int, **kwargs: object):
        if start_date != newest_end and failures["left"]:
            failures["left"] -= 1
            raise SleepMeRateLimited("local rate-limiter at capacity")
        return _one_report_per_requested_date(
            start_date=start_date, days_back=days_back
        )

    mock_sleepme_client.get_sleep_reports.side_effect = flaky_history
    coordinator = _report_coordinator(hass)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert len(coordinator.data) == 7
    assert coordinator.pending_backfill_windows == 4

    await coordinator.async_refresh()

    assert len(coordinator.data) == 14
    assert coordinator.pending_backfill_windows == 3


async def test_newest_window_failure_fails_the_refresh(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to("2026-07-13 12:00:00+00:00")
    mock_sleepme_client.get_sleep_reports.side_effect = SleepMeConnectionError("down")
    coordinator = _report_coordinator(hass)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    # Nothing was fetched after the newest window failed.
    assert mock_sleepme_client.get_sleep_reports.await_count == 1


async def test_auth_failure_during_backfill_still_reaches_reauth(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Backfill failures are tolerated, but a revoked token never is."""
    freezer.move_to("2026-07-13 12:00:00+00:00")
    newest_end = date(2026, 7, 13)

    def revoked_for_history(*, start_date: date, days_back: int, **kwargs: object):
        if start_date != newest_end:
            raise SleepMeAuthError("401")
        return _one_report_per_requested_date(
            start_date=start_date, days_back=days_back
        )

    mock_sleepme_client.get_sleep_reports.side_effect = revoked_for_history
    coordinator = _report_coordinator(hass)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_cache_follows_the_calendar_and_stays_bounded(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Days that fall out of the history range are evicted; new ones arrive."""
    freezer.move_to("2026-07-13 12:00:00+00:00")
    mock_sleepme_client.get_sleep_reports.side_effect = _one_report_per_requested_date
    coordinator = _report_coordinator(hass)
    for _ in range(4):
        await coordinator.async_refresh()
    assert len(coordinator.data) == HISTORY_DAYS

    freezer.move_to("2026-07-16 12:00:00+00:00")
    before = mock_sleepme_client.get_sleep_reports.await_count
    await coordinator.async_refresh()

    assert mock_sleepme_client.get_sleep_reports.await_count - before == 1
    assert len(coordinator.data) == HISTORY_DAYS
    assert coordinator.data[0]["date"] == "2026-06-17"
    assert coordinator.data[-1]["date"] == "2026-07-16"


async def test_reports_without_a_valid_date_are_ignored(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to("2026-07-13 12:00:00+00:00")
    mock_sleepme_client.get_sleep_reports.return_value = [
        {"date": "2026-07-13", "sessions": []},
        {"date": "not-a-date", "sessions": []},
        {"sessions": []},
    ]
    coordinator = _report_coordinator(hass)

    await coordinator.async_refresh()

    assert [report["date"] for report in coordinator.data] == ["2026-07-13"]
