import logging
from .sleepme_api import SleepMeAPI

_LOGGER = logging.getLogger(__name__)


class SleepMeClient:
    """A client for interacting with SleepMe devices."""

    def __init__(self, api_url, token, device_id):
        """Initialize the client."""
        self._api = SleepMeAPI(api_url, token, device_id)
        self.device_id = device_id

    async def get_device_status(self):
        """Get the full status of the device."""
        return await self._api.get_device_status()

    async def set_temperature(self, temperature_c: float) -> bool:
        """Set the target temperature of the device in Celsius."""
        _LOGGER.debug(f"[Device {self.device_id}] Setting temperature to {temperature_c}C")
        payload = {"setTemperatureC": temperature_c}
        response = await self._api.patch_device_control(payload)
        if response and response.get("set_temperature_c") == temperature_c:
            return True
        _LOGGER.warning(
            f"[Device {self.device_id}] Temperature may not have been set to {temperature_c}C. Response: {response}"
        )
        return False

    async def set_power_status(self, is_active: bool) -> bool:
        """Set the power status of the device."""
        target_status = "active" if is_active else "standby"
        _LOGGER.debug(f"[Device {self.device_id}] Setting power status to {target_status}")
        payload = {"thermalControlStatus": target_status}
        response = await self._api.patch_device_control(payload)
        if response and response.get("thermal_control_status") == target_status:
            return True
        _LOGGER.warning(
            f"[Device {self.device_id}] Device status may not have been set to {target_status}. Response: {response}"
        )
        return False

    async def set_schedule_enabled(self, enabled: bool) -> bool:
        """Enable or disable the device's internal schedule."""
        _LOGGER.debug(f"[Device {self.device_id}] Setting schedule enabled to {enabled}")
        payload = {"hasScheduleEnabled": enabled}
        response = await self._api.patch_device_control(payload)
        if response and response.get("has_schedule_enabled") == enabled:
            return True
        _LOGGER.warning(
            f"[Device {self.device_id}] Schedule enabled may not have been set to {enabled}. Response: {response}"
        )
        return False

    async def set_display_brightness(self, brightness_percent: int) -> bool:
        """Set the display brightness."""
        _LOGGER.debug(f"[Device {self.device_id}] Setting brightness to {brightness_percent}%")
        payload = {"brightnessLevel": brightness_percent}
        response = await self._api.patch_device_control(payload)
        return response is not None