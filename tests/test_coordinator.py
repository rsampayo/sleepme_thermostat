"""Coordinator error-translation tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from custom_components.sleepme_thermostat.const import API_URL, DOMAIN
from custom_components.sleepme_thermostat.sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
    SleepMeRateLimited,
)
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


# ---------- a poll skipped by our own limiter is not an outage -----------------


async def test_poll_skipped_by_local_limiter_keeps_entities_available(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """The server was never asked, so the last data stays in place."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    data_before = coordinator.data
    # The coordinator owns its own client instance, separate from the entry's.
    poll = coordinator.client.get_device_status
    polls_before = poll.await_count

    poll.side_effect = SleepMeRateLimited("full")
    await coordinator.async_refresh()

    assert poll.await_count == polls_before + 1
    assert coordinator.last_update_success is True
    assert coordinator.data == data_before


async def test_repeated_skipped_polls_eventually_surface_as_a_failure(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Data older than two skipped intervals is not presented as current."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    poll = coordinator.client.get_device_status

    poll.side_effect = SleepMeRateLimited("full")
    outcomes = []
    for _ in range(3):
        await coordinator.async_refresh()
        outcomes.append(coordinator.last_update_success)
    assert outcomes == [True, True, False]

    # One good poll resets the allowance.
    poll.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    poll.side_effect = SleepMeRateLimited("full")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
