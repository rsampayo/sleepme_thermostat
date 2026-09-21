"""Tests for the SleepMeClient wrapper (sleepme.py).

Patches SleepMeAPI at the call boundary so we exercise the wrapper's:
  - half-degree rounding on set_temp_level
  - response-shape validation on get_device_status / get_claimed_devices
  - status whitelist on set_device_status
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.sleepme_thermostat.sleepme import SleepMeClient
from homeassistant.core import HomeAssistant


@pytest.fixture
def client(hass: HomeAssistant) -> Generator[SleepMeClient]:
    with patch(
        "custom_components.sleepme_thermostat.sleepme.SleepMeAPI",
        autospec=True,
    ) as mock_api_cls:
        # SleepMeClient now resolves transport via SleepMeAPI.get_or_create.
        # autospec'd classmethods return mock_api_cls.<method>.return_value, NOT
        # mock_api_cls.return_value. Wire both so callers find the same instance.
        instance = mock_api_cls.return_value
        instance.api_request = AsyncMock()
        mock_api_cls.get_or_create.return_value = instance
        c = SleepMeClient(hass, "https://api.test/v1", "tok", "dev-1")
        yield c


async def test_set_temp_level_rounds_to_half(client: SleepMeClient) -> None:
    """24.3 -> 24.5 in PATCH payload."""
    client.api.api_request.return_value = {"ok": True}
    await client.set_temp_level(24.3)
    call = client.api.api_request.call_args
    assert call.args == ("PATCH", "devices/dev-1")
    assert call.kwargs["data"] == {"set_temperature_c": 24.5}


async def test_set_temp_level_passes_sentinel(client: SleepMeClient) -> None:
    """-1 (MAX COOL) survives round_half_up because rounding -1 is -1."""
    client.api.api_request.return_value = {"ok": True}
    await client.set_temp_level(-1)
    call = client.api.api_request.call_args
    assert call.kwargs["data"]["set_temperature_c"] == -1


async def test_set_device_status_rejects_unknown(client: SleepMeClient) -> None:
    with pytest.raises(ValueError, match=r"active.*standby"):
        await client.set_device_status("paused")


async def test_set_device_status_active(client: SleepMeClient) -> None:
    client.api.api_request.return_value = {"ok": True}
    await client.set_device_status("active")
    call = client.api.api_request.call_args
    assert call.args == ("PATCH", "devices/dev-1")
    assert call.kwargs["data"] == {"thermal_control_status": "active"}


async def test_set_device_status_standby(client: SleepMeClient) -> None:
    client.api.api_request.return_value = {"ok": True}
    await client.set_device_status("standby")
    call = client.api.api_request.call_args
    assert call.kwargs["data"] == {"thermal_control_status": "standby"}


async def test_get_claimed_devices_rejects_non_list(client: SleepMeClient) -> None:
    client.api.api_request.return_value = {"unexpected": "shape"}
    with pytest.raises(ValueError, match="unexpected response"):
        await client.get_claimed_devices()


async def test_get_device_status_rejects_non_dict(client: SleepMeClient) -> None:
    client.api.api_request.return_value = ["wrong", "shape"]
    with pytest.raises(ValueError, match="unexpected response"):
        await client.get_device_status()


async def test_get_claimed_devices_happy(client: SleepMeClient) -> None:
    client.api.api_request.return_value = [{"id": "dev-1", "name": "Ramon"}]
    result = await client.get_claimed_devices()
    assert result == [{"id": "dev-1", "name": "Ramon"}]


async def test_get_device_status_happy(client: SleepMeClient) -> None:
    payload = {"status": {}, "control": {}, "about": {}}
    client.api.api_request.return_value = payload
    result = await client.get_device_status()
    assert result == payload


async def test_get_sleep_reports_happy(client: SleepMeClient) -> None:
    """Sleep reports use the documented account-scoped query parameters."""
    reports = [{"date": "2026-07-13", "sessions": []}]
    client.api.api_request.return_value = {"reports": reports}

    result = await client.get_sleep_reports(
        start_date=date(2026, 7, 13),
        days_back=6,
        time_zone="Europe/Budapest",
    )

    assert result == reports
    call = client.api.api_request.call_args
    assert call.args == ("GET", "sleep-reports")
    assert call.kwargs["params"] == {
        "start_date": "2026-07-13",
        "days_back": 6,
        "time_zone": "Europe/Budapest",
    }


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"reports": {}}, {"reports": ["not-a-report"]}],
)
async def test_get_sleep_reports_rejects_bad_shapes(
    client: SleepMeClient, payload: object
) -> None:
    """Malformed report responses fail closed instead of poisoning entities."""
    client.api.api_request.return_value = payload
    with pytest.raises(ValueError, match="unexpected response"):
        await client.get_sleep_reports(
            start_date=date(2026, 7, 13),
            days_back=6,
            time_zone="Europe/Budapest",
        )
