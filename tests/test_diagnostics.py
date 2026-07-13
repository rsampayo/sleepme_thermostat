"""Tests for the diagnostics platform."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.sleepme_thermostat.const import DOMAIN
from custom_components.sleepme_thermostat.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN, MOCK_DEVICE_ID, MOCK_NAME


def _make_v4_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_diag",
        version=4,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_token": MOCK_API_TOKEN,
            "device_id": MOCK_DEVICE_ID,
            "firmware_version": "0.0.0-test",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "TEST-SERIAL",
        },
        options={"scan_interval": 30},
    )


async def test_diagnostics_redacts_token(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """The api_token is replaced with the redaction sentinel."""
    entry = _make_v4_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["data"]["api_token"] == "**REDACTED**"
    # Non-secret keys survive.
    assert diag["entry"]["data"]["device_id"] == MOCK_DEVICE_ID
    # mac_address is in TO_REDACT (defensive); should also be redacted.
    assert diag["entry"]["data"]["mac_address"] == "**REDACTED**"


async def test_diagnostics_structure(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Top-level keys are stable; coordinator snapshot is present."""
    entry = _make_v4_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert set(diag.keys()) == {
        "entry",
        "device_info",
        "coordinator",
        "report_coordinator",
    }
    assert diag["entry"]["version"] == 5
    assert diag["entry"]["title"] == f"Dock Pro {MOCK_NAME}"
    assert diag["entry"]["options"]["scan_interval"] == 30
    assert diag["coordinator"]["last_update_success"] is True
    assert diag["coordinator"]["update_interval_seconds"] == 30
    assert set(diag["coordinator"]["data"].keys()) == {"status", "control", "about"}
    assert diag["report_coordinator"] is None


async def test_diagnostics_handles_missing_entry_data(
    hass: HomeAssistant,
) -> None:
    """If entry never reached setup, diagnostics still returns gracefully."""
    entry = _make_v4_entry()
    # Note: NOT calling async_setup — entry is registered but not loaded.
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["data"]["api_token"] == "**REDACTED**"
    assert diag["coordinator"] == {}
    assert diag["report_coordinator"] is None


async def test_tracker_diagnostics_never_include_health_payload(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
) -> None:
    """Support bundles expose report health/counts but no sessions or hypnograms."""
    mock_sleepme_client.get_device_status.return_value = tracker_status
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_tracker_diag",
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
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["report_coordinator"] == {
        "update_interval_seconds": 1800,
        "last_update_success": True,
        "last_exception": None,
        "report_count": 3,
    }
    assert "sessions" not in str(diag["report_coordinator"])
    assert "hypnogram" not in str(diag["report_coordinator"])
