"""High-level SleepMe API client.

Thin wrapper over SleepMeAPI. Raises typed exceptions from sleepme_api on
failure — does not swallow errors. Callers (coordinator, config_flow,
climate command path) translate them into HA-framework exceptions.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant

from .helpers import round_half_up
from .sleepme_api import SleepMeAPI


class SleepMeClient:
    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        device_id: str | None = None,
    ) -> None:
        self.api_url = api_url
        self.token = token
        self.device_id = device_id
        self.api = SleepMeAPI.get_or_create(hass, api_url, token)

    async def set_temp_level(self, temp_c: float, retries: int = 2) -> dict:
        """Set the temperature level in Celsius."""
        temp_c = round_half_up(temp_c)
        endpoint = f"devices/{self.device_id}"
        data = {"set_temperature_c": temp_c}
        return await self.api.api_request("PATCH", endpoint, data=data, retries=retries)

    async def set_device_status(self, status: str, retries: int = 2) -> dict:
        """Set the device status to 'active' (on) or 'standby' (off)."""
        if status not in ("active", "standby"):
            raise ValueError("Status must be either 'active' or 'standby'.")
        endpoint = f"devices/{self.device_id}"
        data = {"thermal_control_status": status}
        return await self.api.api_request("PATCH", endpoint, data=data, retries=retries)

    async def get_claimed_devices(self, retries: int = 1) -> list:
        """Return a list of claimed devices for the configured token."""
        response = await self.api.api_request("GET", "devices", retries=retries)
        if not isinstance(response, list):
            raise ValueError(f"unexpected response for claimed devices: {response!r}")
        return response

    async def get_device_status(self, retries: int = 0) -> dict:
        """Retrieve the device status."""
        endpoint = f"devices/{self.device_id}"
        response = await self.api.api_request("GET", endpoint, retries=retries)
        if not isinstance(response, dict):
            raise ValueError(f"unexpected response for device status: {response!r}")
        return response

    async def get_sleep_reports(
        self,
        *,
        start_date: date,
        days_back: int,
        time_zone: str,
        retries: int = 0,
    ) -> list[dict]:
        """Return account-scoped sleep reports ending on ``start_date``."""
        response = await self.api.api_request(
            "GET",
            "sleep-reports",
            params={
                "start_date": start_date.isoformat(),
                "days_back": days_back,
                "time_zone": time_zone,
            },
            retries=retries,
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("reports"), list
        ):
            raise ValueError(f"unexpected response for sleep reports: {response!r}")
        if not all(isinstance(report, dict) for report in response["reports"]):
            raise ValueError(f"unexpected response for sleep reports: {response!r}")
        return response["reports"]
