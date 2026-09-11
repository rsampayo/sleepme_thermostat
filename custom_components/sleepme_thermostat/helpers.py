"""Shared helpers used across multiple platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .const import (
    DOMAIN,
    MAX_TEMP_C,
    MIN_TEMP_C,
    PRESET_MAX_COOL,
    PRESET_MAX_HEAT,
    PRESET_TEMPERATURES,
)


def round_half_up(n: float) -> float:
    """Round a number to the nearest .0 or .5."""
    return round(n * 2) / 2


_SENTINEL_TO_LIMIT: dict[int | float, float] = {
    PRESET_TEMPERATURES[PRESET_MAX_COOL]: MIN_TEMP_C,
    PRESET_TEMPERATURES[PRESET_MAX_HEAT]: MAX_TEMP_C,
}


def clamp_api_sentinel(value: float | None) -> float | None:
    """Map API sentinel temperatures to their physical limits.

    The SleepMe API uses -1 for MAX COLD and 999 for MAX HEAT.
    HA should see the device's actual boundary (13.0 / 48.0 C) instead.
    """
    if value is None:
        return None
    return _SENTINEL_TO_LIMIT.get(value, value)


def build_device_info(device_id: str, display_name: str, info: dict) -> DeviceInfo:
    """Construct the device_info dict shared by every platform.

    `display_name` is the full user-facing device name (e.g. "Dock Pro Ramon").
    Callers typically pass `entry.title`.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=display_name,
        manufacturer="SleepMe",
        model=info.get("model"),
        sw_version=info.get("firmware_version"),
        connections={(CONNECTION_NETWORK_MAC, info.get("mac_address", ""))},
        serial_number=info.get("serial_number"),
    )
