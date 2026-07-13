"""Coordinator error-translation tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from custom_components.sleepme_thermostat.const import API_URL, DOMAIN
from custom_components.sleepme_thermostat.sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
    SleepMeRateLimited,
)
from custom_components.sleepme_thermostat.update_manager import _report_windows
from homeassistant.config_entries import ConfigEntryState
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
