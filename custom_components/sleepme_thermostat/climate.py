"""Climate entity for the SleepMe Dock Pro.

Phase 3 changes the command path to optimistic state + one PATCH per user
action, replacing the verify-after-command retry loop that historically caused
the cascading 429 / multi-minute UI spinner problem.

Behavior contract:
- A command costs exactly one request: the PATCH. No verification loop, no
  refresh afterwards, no fixed retries on top of the transport layer's own
  backoff. The per-account budget is nine requests a minute shared with every
  poll, so a second request per click is what used to exhaust it.
- The expected new state is written locally first (`_optimistic_*`
  attributes), so the UI answers at once. The next regular poll reconciles. A
  failed PATCH rolls the optimistic value back.
- Rapid setpoint changes coalesce. Each call waits COMMAND_DEBOUNCE_SECONDS and
  only the newest one sends, so four clicks on the up arrow are one PATCH
  carrying the final value. A superseded call returns quietly.
- Out-of-range temps raise ServiceValidationError (toast in HA UI).
- Transport failures during PATCH raise HomeAssistantError (toast).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    PRESET_NONE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MAX_TEMP_C,
    MIN_TEMP_C,
    PRESET_MAX_COOL,
    PRESET_MAX_HEAT,
    PRESET_TEMPERATURES,
)
from .helpers import build_device_info, clamp_api_sentinel, round_half_up
from .sleepme_api import (
    SleepMeAPIError,
    SleepMeAuthError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from .sleepme import SleepMeClient
    from .update_manager import SleepMeUpdateManager

_LOGGER = logging.getLogger(__name__)

# How long to trust our optimistic local state before falling back to whatever
# the coordinator reports. The next regular poll is what reconciles it, so the
# window is never shorter than one poll interval plus a buffer for the request
# in flight.
OPTIMISTIC_WINDOW = timedelta(seconds=30)
OPTIMISTIC_POLL_BUFFER = timedelta(seconds=10)

# How long a setpoint change waits for a newer one before it is sent.
COMMAND_DEBOUNCE_SECONDS = 1.5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SleepMe Thermostat climate entity from a config entry."""
    device_id: str = entry.data["device_id"]
    data = entry.runtime_data
    device_info = build_device_info(device_id, entry.title, data.device_info)

    _LOGGER.debug(
        "[Device %s] Setting up SleepMeThermostat entity (%s)",
        device_id,
        entry.title,
    )
    async_add_entities(
        [SleepMeThermostat(data.coordinator, data.client, device_id, device_info)]
    )


class SleepMeThermostat(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_name = None  # primary entity — friendly name == device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO]
    _attr_preset_modes = [PRESET_NONE, PRESET_MAX_HEAT, PRESET_MAX_COOL]
    _attr_min_temp = MIN_TEMP_C
    _attr_max_temp = MAX_TEMP_C

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        client: SleepMeClient,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_thermostat"
        self._attr_device_info = device_info

        # Optimistic state — used between a successful PATCH and the next
        # coordinator poll that confirms the change.
        self._optimistic_target_temp: float | None = None
        self._optimistic_target_temp_until: datetime | None = None
        self._optimistic_status: str | None = None
        self._optimistic_status_until: datetime | None = None

        # Last user-requested temperature, used to restore from a preset.
        self._previous_target_temperature: float | None = None

        # Bumped by every setpoint request; only the newest one sends.
        self._setpoint_request_id = 0

    # ---------- read properties -------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        water_temp_c = self.coordinator.data["status"].get("water_temperature_c")
        # Gen-2 / Chilipad 2.0 units report -1 for water_temperature_c (and _f)
        # while idle in standby — a "no reading" sentinel, not a real
        # sub-zero water bath. Surface it as unknown rather than -1 C.
        if water_temp_c is not None and water_temp_c < 0:
            return None
        return water_temp_c

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature, clamping API sentinels to physical limits."""
        return clamp_api_sentinel(self._raw_setpoint())

    @property
    def hvac_mode(self) -> HVACMode:
        status = self._effective_thermal_status()
        return HVACMode.AUTO if status == "active" else HVACMode.OFF

    @property
    def preset_mode(self) -> str:
        """Map the current setpoint back to a preset, if it is a sentinel."""
        if self.hvac_mode == HVACMode.OFF:
            return PRESET_NONE
        setpoint = self._raw_setpoint()
        for mode, sentinel in PRESET_TEMPERATURES.items():
            if setpoint == sentinel:
                return mode
        return PRESET_NONE

    def _raw_setpoint(self) -> float | None:
        """Resolve the current setpoint including sentinel values."""
        server_value = self.coordinator.data["control"].get("set_temperature_c")
        optimistic = self._effective_optimistic_temp(server_value)
        return optimistic if optimistic is not None else server_value

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        return bool(self.coordinator.data["status"].get("is_connected", False))

    # ---------- command handlers -----------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            # ATTR_TEMPERATURE == "temperature" — HA's service schema guarantees this.
            raise ServiceValidationError(
                "Temperature is required",
                translation_domain=DOMAIN,
                translation_key="temperature_required",
            )

        # Sentinel values from the API contract are always allowed; other values
        # must fit the documented range.
        if target_temp not in PRESET_TEMPERATURES.values() and not (
            MIN_TEMP_C <= target_temp <= MAX_TEMP_C
        ):
            raise ServiceValidationError(
                f"Temperature {target_temp}°C is outside the allowed range "
                f"{MIN_TEMP_C}-{MAX_TEMP_C}°C",
                translation_domain=DOMAIN,
                translation_key="temperature_out_of_range",
                translation_placeholders={
                    "value": str(target_temp),
                    "min": str(MIN_TEMP_C),
                    "max": str(MAX_TEMP_C),
                },
            )

        # Round to half-degree, matching the API spec.
        if target_temp not in PRESET_TEMPERATURES.values():
            target_temp = round_half_up(target_temp)

        # Show the new value at once, then give a newer request the chance to
        # replace this one before anything is sent.
        self._setpoint_request_id += 1
        request_id = self._setpoint_request_id
        self._set_optimistic_target(target_temp)
        self.async_write_ha_state()

        await asyncio.sleep(COMMAND_DEBOUNCE_SECONDS)
        if request_id != self._setpoint_request_id:
            return

        _LOGGER.info(
            "[Device %s] Setting target temperature to %s°C",
            self._device_id,
            target_temp,
        )

        try:
            await self._fire_patch(
                self._client.set_temp_level(target_temp),
                description=f"set_temperature={target_temp}",
            )
        except HomeAssistantError:
            if request_id == self._setpoint_request_id:
                self._optimistic_target_temp = None
                self._optimistic_target_temp_until = None
                self.async_write_ha_state()
            raise

        # Remember the explicit user request for preset → "None" restore.
        if target_temp not in PRESET_TEMPERATURES.values():
            self._previous_target_temperature = target_temp

        # Restart the window from the moment the device was actually told.
        if request_id == self._setpoint_request_id:
            self._set_optimistic_target(target_temp)
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in (HVACMode.AUTO, HVACMode.OFF):
            return

        target_status = "active" if hvac_mode == HVACMode.AUTO else "standby"

        self._optimistic_status = target_status
        self._optimistic_status_until = dt_util.utcnow() + self._optimistic_window()
        self.async_write_ha_state()

        try:
            await self._fire_patch(
                self._client.set_device_status(target_status),
                description=f"set_status={target_status}",
            )
        except HomeAssistantError:
            self._optimistic_status = None
            self._optimistic_status_until = None
            self.async_write_ha_state()
            raise

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switching to a preset is implemented as setting the sentinel temp."""
        # Engage HVAC AUTO first if the user picked a preset while off.
        if self.hvac_mode == HVACMode.OFF and preset_mode != PRESET_NONE:
            await self.async_set_hvac_mode(HVACMode.AUTO)

        if preset_mode in PRESET_TEMPERATURES:
            raw = self._raw_setpoint()
            if raw is not None and raw not in PRESET_TEMPERATURES.values():
                self._previous_target_temperature = self.target_temperature
            await self.async_set_temperature(
                temperature=PRESET_TEMPERATURES[preset_mode]
            )
        elif preset_mode == PRESET_NONE:
            # Restore the last real target the user picked, or fall back to
            # the current measured water temperature so the slider lands somewhere
            # reasonable.
            restore = self._previous_target_temperature
            if restore is None:
                restore = self.current_temperature
            if restore is not None:
                await self.async_set_temperature(temperature=restore)

    # ---------- internals -------------------------------------------------------

    def _optimistic_window(self) -> timedelta:
        """Return how long an optimistic value outlives the command.

        No refresh follows a command, so the value has to survive until the
        next regular poll, however long the configured interval is.
        """
        poll_interval = self.coordinator.update_interval or timedelta(0)
        return max(OPTIMISTIC_WINDOW, poll_interval + OPTIMISTIC_POLL_BUFFER)

    def _set_optimistic_target(self, target_temp: float) -> None:
        self._optimistic_target_temp = target_temp
        self._optimistic_target_temp_until = (
            dt_util.utcnow() + self._optimistic_window()
        )

    async def _fire_patch(self, coro: Awaitable[Any], *, description: str) -> None:
        """Run a PATCH coroutine, translating transport errors to HA errors.

        Auth errors are NOT raised here — those should reach the coordinator
        loop which handles them via the reauth flow.
        """
        try:
            await coro
        except SleepMeAuthError as err:
            # The coordinator will detect this on its next poll and trigger reauth.
            # We still surface it as a HomeAssistantError so the user sees the
            # immediate command failed.
            raise HomeAssistantError(
                "SleepMe API token rejected - entry will request reauthentication"
            ) from err
        except SleepMeAPIError as err:
            raise HomeAssistantError(
                f"SleepMe API command '{description}' failed: {err}"
            ) from err

    def _effective_optimistic_temp(self, server_value: float | None) -> float | None:
        """Return the optimistic target if it should still win, else None.

        Clears the optimistic value when the server confirms it or the
        OPTIMISTIC_WINDOW expires.
        """
        if self._optimistic_target_temp is None:
            return None
        now = dt_util.utcnow()
        if (
            self._optimistic_target_temp_until is not None
            and now > self._optimistic_target_temp_until
        ):
            # If the coordinator hasn't reconciled successfully yet, hold the
            # optimistic value rather than snap back to a stale server read.
            if not self.coordinator.last_update_success:
                return self._optimistic_target_temp
            self._optimistic_target_temp = None
            self._optimistic_target_temp_until = None
            return None
        if server_value == self._optimistic_target_temp:
            self._optimistic_target_temp = None
            self._optimistic_target_temp_until = None
            return None
        return self._optimistic_target_temp

    def _effective_thermal_status(self) -> str | None:
        """Return the optimistic status if it should still win, else server."""
        server_value = self.coordinator.data["control"].get("thermal_control_status")
        if self._optimistic_status is None:
            return server_value
        now = dt_util.utcnow()
        if (
            self._optimistic_status_until is not None
            and now > self._optimistic_status_until
        ):
            # See _effective_optimistic_temp for rationale.
            if not self.coordinator.last_update_success:
                return self._optimistic_status
            self._optimistic_status = None
            self._optimistic_status_until = None
            return server_value
        if server_value == self._optimistic_status:
            self._optimistic_status = None
            self._optimistic_status_until = None
            return server_value
        return self._optimistic_status
