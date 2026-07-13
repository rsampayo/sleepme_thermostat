"""Global fixtures for sleepme_thermostat tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the sleepme_thermostat custom integration in tests."""
    yield


@pytest.fixture
def tracker_status() -> dict:
    """Return the fabricated ST501NA device-status fixture."""
    return json.loads((FIXTURES / "tracker_status.json").read_text())


@pytest.fixture
def sleep_reports() -> list[dict]:
    """Return fabricated sleep reports matching the live public API schema."""
    payload = json.loads((FIXTURES / "sleep_reports.json").read_text())
    return payload["reports"]


@pytest.fixture
def mock_sleepme_client(sleep_reports: list[dict]) -> Generator[AsyncMock]:
    """Mock SleepMeClient so no real network calls happen.

    Patches both import sites:
      - custom_components.sleepme_thermostat.SleepMeClient   (used by __init__.py)
      - custom_components.sleepme_thermostat.update_manager.SleepMeClient
    so the coordinator's internal instantiation is also caught.
    """
    healthy_status = {
        "status": {
            "water_temperature_c": 22.0,
            "is_water_low": False,
            "is_connected": True,
            "water_level": 78,
        },
        "control": {
            "set_temperature_c": 22.0,
            "thermal_control_status": "standby",
            "brightness_level": 50,
            "display_temperature_unit": "c",
            "time_zone": "America/Mexico_City",
        },
        "about": {
            "firmware_version": "0.0.0-test",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "TEST-SERIAL",
            "ip_address": "192.168.1.100",
            "lan_address": "192.168.1.100",
        },
    }
    with (
        patch(
            "custom_components.sleepme_thermostat.SleepMeClient",
            autospec=True,
        ) as mock_init,
        patch(
            "custom_components.sleepme_thermostat.update_manager.SleepMeClient",
            autospec=True,
        ) as mock_um,
    ):
        instance = AsyncMock()
        instance.get_device_status = AsyncMock(return_value=healthy_status)
        instance.get_claimed_devices = AsyncMock(return_value=[])
        instance.get_sleep_reports = AsyncMock(return_value=sleep_reports)
        instance.set_temp_level = AsyncMock(return_value={})
        instance.set_device_status = AsyncMock(return_value={})
        mock_init.return_value = instance
        mock_um.return_value = instance
        yield instance
