"""Tests for the climate entity: optimistic state, validation, preset mode."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from custom_components.sleepme_thermostat.const import (
    API_URL,
    DOMAIN,
    MAX_TEMP_C,
    MIN_TEMP_C,
    PRESET_MAX_COOL,
    PRESET_MAX_HEAT,
)
from custom_components.sleepme_thermostat.sleepme_api import (
    SleepMeConnectionError,
    SleepMeRateLimited,
)
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN, MOCK_DEVICE_ID, MOCK_NAME

ENTITY_ID = f"climate.dock_pro_{MOCK_NAME.lower().replace(' ', '_')}"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_climate",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": MOCK_API_TOKEN,
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "1.0",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "SN-1",
        },
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_target_temperature_is_optimistic_after_set(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """After PATCH succeeds, target_temperature returns the new value immediately."""
    await _setup(hass)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["temperature"] == 22.0  # from mock fixture

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Optimistic value should now be 25, even though the mocked coordinator
    # still reports 22 (mock fixture doesn't update on PATCH).
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["temperature"] == 25.0


async def test_set_temperature_out_of_range_raises(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Values outside MIN_TEMP_C..MAX_TEMP_C raise ServiceValidationError.

    Note: HA's climate platform also does range validation at the service layer
    using the entity's min_temp/max_temp; ServiceValidationError is raised
    regardless of which layer catches it.
    """
    await _setup(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: MAX_TEMP_C + 0.5},
            blocking=True,
        )

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: MIN_TEMP_C - 0.5},
            blocking=True,
        )

    # Sentinels (-1 / 999) are blocked by HA's service-layer range check;
    # the only way they reach our code is via async_set_preset_mode (see
    # test_preset_mode_max_cool). That path is tested separately.


async def test_set_temperature_transport_failure_raises_ha_error(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """SleepMeRateLimited (or any transport error) surfaces as HomeAssistantError."""
    await _setup(hass)
    # Make set_temp_level raise on next call.
    mock_sleepme_client.set_temp_level.side_effect = SleepMeRateLimited("at capacity")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.0},
            blocking=True,
        )


async def test_set_temperature_connection_error_raises_ha_error(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """SleepMeConnectionError on PATCH surfaces as HomeAssistantError."""
    await _setup(hass)
    mock_sleepme_client.set_temp_level.side_effect = SleepMeConnectionError("dns")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.0},
            blocking=True,
        )


async def test_set_hvac_mode_optimistic(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """async_set_hvac_mode writes optimistic state AND fires the right PATCH."""
    await _setup(hass)
    mock_sleepme_client.set_device_status.reset_mock()
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.OFF  # mock fixture has standby

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.AUTO},
        blocking=True,
    )
    await hass.async_block_till_done()

    mock_sleepme_client.set_device_status.assert_called_once_with("active")
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.AUTO


async def test_preset_mode_max_cool(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Setting MAX_COOL preset PATCHes the -1 sentinel and updates preset_mode."""
    await _setup(hass)
    mock_sleepme_client.set_temp_level.reset_mock()
    mock_sleepme_client.set_device_status.reset_mock()

    # Ramon is currently OFF — preset switch should also turn AUTO on.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: PRESET_MAX_COOL},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Engaged HVAC AUTO (was OFF) AND patched the -1 sentinel — both must fire.
    mock_sleepme_client.set_device_status.assert_called_once_with("active")
    mock_sleepme_client.set_temp_level.assert_called_once_with(-1)

    state = hass.states.get(ENTITY_ID)
    # Optimistic temp == sentinel; preset_mode derives from that.
    assert state.attributes["temperature"] == -1
    assert state.attributes["preset_mode"] == PRESET_MAX_COOL


async def test_preset_mode_none_restores_previous_temp(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Setting PRESET_NONE restores the previously-explicit target."""
    await _setup(hass)

    # Set an explicit temp first.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 24.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Then engage a preset, then revoke it.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: PRESET_MAX_HEAT},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["preset_mode"] == PRESET_MAX_HEAT

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: "none"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes["temperature"] == 24.0
    assert state.attributes["preset_mode"] == "none"


async def test_set_temperature_calls_patch_exactly_once(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """A single user action fires exactly one PATCH — no verify-loop retries."""
    await _setup(hass)
    mock_sleepme_client.set_temp_level.reset_mock()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert mock_sleepme_client.set_temp_level.call_count == 1


async def test_round_half_up_applied_to_user_temp(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """User-submitted 24.3 PATCHes 24.5 (half-degree rounding)."""
    await _setup(hass)
    mock_sleepme_client.set_temp_level.reset_mock()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 24.3},
        blocking=True,
    )
    await hass.async_block_till_done()

    call = mock_sleepme_client.set_temp_level.call_args
    assert call.args[0] == 24.5


async def test_current_temperature_passthrough(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """current_temperature reads from coordinator.data['status']."""
    await _setup(hass)
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["current_temperature"] == 22.0


async def test_current_temperature_negative_sentinel_is_unknown(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Gen-2 units report water_temperature_c == -1 in standby; surface it as
    unknown rather than a bogus sub-zero reading. See issue #46."""
    entry = await _setup(hass)
    coord = entry.runtime_data.coordinator
    coord.data["status"]["water_temperature_c"] = -1
    coord.async_update_listeners()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["current_temperature"] is None


async def test_available_false_when_coordinator_unsuccessful(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """available returns False when coordinator.last_update_success is False."""
    entry = await _setup(hass)
    coord = entry.runtime_data.coordinator
    coord.last_update_success = False
    coord.async_update_listeners()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == "unavailable"


async def test_available_false_when_disconnected(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """available returns False when coordinator reports is_connected=False."""
    entry = await _setup(hass)
    coord = entry.runtime_data.coordinator
    coord.data["status"]["is_connected"] = False
    coord.async_update_listeners()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == "unavailable"


async def test_optimistic_window_expires(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """After OPTIMISTIC_WINDOW (30s) the coordinator's value wins again.

    Asserts the internal _optimistic_target_temp clears after the window
    expires and the next property read returns the coordinator value.
    """
    from datetime import timedelta
    from unittest.mock import patch as _patch

    from homeassistant.util import dt as dt_util

    entry = await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.0},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["temperature"] == 25.0  # optimistic wins now

    # Fast-forward past the window and force a re-render.
    future = dt_util.utcnow() + timedelta(seconds=61)
    with _patch(
        "custom_components.sleepme_thermostat.climate.dt_util.utcnow",
        return_value=future,
    ):
        # Hitting the coordinator's listeners triggers a state re-write.
        # Phase 6: optimistic holds while coordinator is unsuccessful, so the
        # snap-back only fires when last_update_success is True.
        coord = entry.runtime_data.coordinator
        coord.last_update_success = True
        coord.async_update_listeners()
        await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    # Coordinator's mock still reports 22.0; optimistic is gone.
    assert state.attributes["temperature"] == 22.0
