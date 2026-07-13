"""Tests for the lossless on-demand sleep-report action."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from custom_components.sleepme_thermostat.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS_BACK,
    ATTR_START_DATE,
    ATTR_TIME_ZONE,
    DOMAIN,
    SERVICE_GET_SLEEP_REPORTS,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN


def _tracker_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_tracker_service",
        version=5,
        unique_id="tracker-device",
        title="Sleep Tracker Bedroom",
        data={
            "api_token": MOCK_API_TOKEN,
            "device_id": "tracker-device",
            "firmware_version": "2.3.4-test",
            "mac_address": "11:22:33:44:55:66",
            "model": "ST501NA",
            "serial_number": "TRACKER-TEST-SERIAL",
        },
    )


async def test_get_sleep_reports_returns_raw_payload(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
    sleep_reports: list[dict],
) -> None:
    """The response action preserves sessions and hypnogram segments exactly."""
    mock_sleepme_client.get_device_status.return_value = tracker_status
    entry = _tracker_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_SLEEP_REPORTS,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_START_DATE: "2026-07-13",
            ATTR_DAYS_BACK: 6,
            ATTR_TIME_ZONE: "Europe/Budapest",
        },
        blocking=True,
        return_response=True,
    )

    assert response == {"reports": sleep_reports}
    call = mock_sleepme_client.get_sleep_reports.await_args
    assert call.kwargs == {
        "start_date": date(2026, 7, 13),
        "days_back": 6,
        "time_zone": "Europe/Budapest",
    }


async def test_get_sleep_reports_rejects_unknown_entry(
    hass: HomeAssistant,
) -> None:
    """An explicit loaded config entry is required for predictable routing."""
    from custom_components.sleepme_thermostat import async_setup

    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="not found"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_SLEEP_REPORTS,
            {ATTR_CONFIG_ENTRY_ID: "missing-entry"},
            blocking=True,
            return_response=True,
        )
