"""Validate shipped automation blueprints after input substitution."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from custom_components.sleepme_thermostat.const import DOMAIN
from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    ValidationStatus,
    async_validate_config_item,
)
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.generated.languages import LANGUAGES
from homeassistant.helpers import translation
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

BLUEPRINTS = (
    Path(__file__).parents[1] / "blueprints" / "automation" / "sleepme_thermostat"
)
STRINGS = Path(__file__).parents[1] / "custom_components" / DOMAIN / "strings.json"

BLUEPRINT_INPUTS = {
    "tracker_occupancy_actions.yaml": {
        "occupancy_sensor": "binary_sensor.sleepme_user_detected",
    },
    "dock_presence_control.yaml": {
        "occupancy_sensor": "binary_sensor.sleepme_user_detected",
        "dock_climate": "climate.sleepme_dock",
    },
    "dock_back_to_sleep.yaml": {
        "occupancy_sensor": "binary_sensor.sleepme_user_detected",
        "dock_climate": "climate.sleepme_dock",
    },
    "tracker_warm_awake.yaml": {
        "occupancy_sensor": "binary_sensor.sleepme_user_detected",
        "dock_climate": "climate.sleepme_dock",
    },
    "sleep_report_alert.yaml": {
        "report_date_sensor": "sensor.sleepme_last_report",
        "score_sensor": "sensor.sleepme_score",
        "duration_sensor": "sensor.sleepme_duration",
        "efficiency_sensor": "sensor.sleepme_efficiency",
        "latency_sensor": "sensor.sleepme_latency",
        "deep_sleep_sensor": "sensor.sleepme_deep_sleep",
        "alert_actions": [
            {
                "action": "persistent_notification.create",
                "data": {"message": "{{ sleepme_alert_message }}"},
            }
        ],
    },
}


def _substituted_config(filename: str, overrides: dict | None = None) -> dict:
    """Load a blueprint and replace all input tags with test values."""
    path = BLUEPRINTS / filename
    blueprint = Blueprint(
        yaml_util.load_yaml(path),
        path=str(path),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    values = {**BLUEPRINT_INPUTS[filename], **(overrides or {})}
    inputs = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": f"sleepme_thermostat/{filename}",
                "input": values,
            }
        },
    )
    inputs.validate()
    return inputs.async_substitute()


@pytest.mark.parametrize("filename", sorted(BLUEPRINT_INPUTS))
async def test_blueprint_is_valid_after_substitution(
    hass: HomeAssistant, filename: str
) -> None:
    """Metadata, selectors, triggers, templates, and actions satisfy HA schemas."""
    path = BLUEPRINTS / filename
    blueprint = Blueprint(
        yaml_util.load_yaml(path),
        path=str(path),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.validate() is None

    config = _substituted_config(filename)
    validated = await async_validate_config_item(hass, filename, config)

    assert validated is not None
    assert validated.validation_status is ValidationStatus.OK


async def test_occupancy_blueprint_runs_both_action_branches(
    hass: HomeAssistant,
) -> None:
    """Confirmed bed entry and exit invoke their independent action selectors."""
    occupied_calls = async_mock_service(hass, "test", "occupied")
    empty_calls = async_mock_service(hass, "test", "empty")
    occupancy = "binary_sensor.sleepme_user_detected"
    hass.states.async_set(occupancy, "off")
    config = _substituted_config(
        "tracker_occupancy_actions.yaml",
        {
            "occupied_delay": {"seconds": 0},
            "empty_delay": {"seconds": 0},
            "occupied_actions": [{"action": "test.occupied"}],
            "empty_actions": [{"action": "test.empty"}],
        },
    )
    config.update({"id": "test_occupancy", "alias": "Test occupancy"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    hass.states.async_set(occupancy, "on")
    await hass.async_block_till_done()
    hass.states.async_set(occupancy, "off")
    await hass.async_block_till_done()

    assert len(occupied_calls) == 1
    assert len(empty_calls) == 1


async def test_presence_control_blueprint_starts_and_stops_dock(
    hass: HomeAssistant,
) -> None:
    """Occupancy within the active window sets mode/temperature, then stops."""
    mode_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    temperature_calls = async_mock_service(hass, "climate", "set_temperature")
    off_calls = async_mock_service(hass, "climate", "turn_off")
    occupancy = "binary_sensor.sleepme_user_detected"
    hass.states.async_set(occupancy, "off")
    config = _substituted_config(
        "dock_presence_control.yaml",
        {
            "sleep_start_time": "00:00:00",
            "sleep_end_time": "23:59:59",
            "early_start_window": 0,
            "target_temperature": 20.5,
            "empty_delay": {"seconds": 0},
        },
    )
    config.update({"id": "test_presence", "alias": "Test presence"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    hass.states.async_set(occupancy, "on")
    await hass.async_block_till_done()

    assert len(mode_calls) == 1
    assert mode_calls[0].data["hvac_mode"] == "auto"
    assert len(temperature_calls) == 1
    assert temperature_calls[0].data["temperature"] == 20.5

    hass.states.async_set(occupancy, "off")
    await hass.async_block_till_done()
    assert len(off_calls) == 1
    await hass.services.async_call(
        "automation",
        "turn_off",
        {"entity_id": "automation.test_presence"},
        blocking=True,
    )


async def test_presence_control_extends_an_occupied_wake_time(
    hass: HomeAssistant,
) -> None:
    """An occupied bed delays scheduled shutdown by the configured extension."""
    off_calls = async_mock_service(hass, "climate", "turn_off")
    occupancy = "binary_sensor.sleepme_user_detected"
    await hass.config.async_set_time_zone("UTC")
    trigger_time = (dt_util.utcnow() + timedelta(minutes=1)).replace(
        second=0, microsecond=0
    )
    hass.states.async_set(occupancy, "on")
    config = _substituted_config(
        "dock_presence_control.yaml",
        {
            "sleep_end_time": trigger_time.strftime("%H:%M:%S"),
            "occupied_wake_extension": {"minutes": 1},
        },
    )
    config.update({"id": "test_snooze", "alias": "Test snooze"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    async_fire_time_changed(hass, trigger_time + timedelta(seconds=1), fire_all=True)
    for _ in range(5):
        await asyncio.sleep(0)
    assert not off_calls

    async_fire_time_changed(hass, trigger_time + timedelta(seconds=62))
    await hass.async_block_till_done()
    await hass.services.async_call(
        "automation",
        "turn_off",
        {"entity_id": "automation.test_snooze"},
        blocking=True,
    )

    assert len(off_calls) == 1


async def test_back_to_sleep_blueprint_adjusts_then_restores(
    hass: HomeAssistant,
) -> None:
    """An overnight absence and return applies the signed temporary adjustment."""
    mode_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    temperature_calls = async_mock_service(hass, "climate", "set_temperature")
    occupancy = "binary_sensor.sleepme_user_detected"
    dock = "climate.sleepme_dock"
    hass.states.async_set(occupancy, "on")
    hass.states.async_set(dock, "auto", {"temperature": 20.0})
    config = _substituted_config(
        "dock_back_to_sleep.yaml",
        {
            "active_start_time": "00:00:00",
            "active_end_time": "23:59:59",
            "minimum_absence": {"seconds": 0},
            "return_timeout": {"minutes": 1},
            "temperature_adjustment": -1.5,
            "adjustment_duration": {"seconds": 0},
        },
    )
    config.update({"id": "test_return", "alias": "Test return"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    hass.states.async_set(occupancy, "off")
    # Let the automation reach wait_for_trigger without waiting on its timeout.
    for _ in range(5):
        await asyncio.sleep(0)
    hass.states.async_set(occupancy, "on")
    await hass.async_block_till_done()

    assert len(mode_calls) == 1
    assert [call.data["temperature"] for call in temperature_calls] == [18.5, 20.0]


async def test_warm_awake_blueprint_heats_occupied_bed_then_stops(
    hass: HomeAssistant,
) -> None:
    """Warm Awake starts at the configured offset and ends after its duration."""
    mode_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    temperature_calls = async_mock_service(hass, "climate", "set_temperature")
    off_calls = async_mock_service(hass, "climate", "turn_off")
    occupancy = "binary_sensor.sleepme_user_detected"
    dock = "climate.sleepme_dock"
    await hass.config.async_set_time_zone("UTC")
    trigger_time = (dt_util.utcnow() + timedelta(minutes=1)).replace(
        second=0, microsecond=0
    )
    wake_time = (trigger_time + timedelta(minutes=15)).strftime("%H:%M:%S")
    hass.states.async_set(occupancy, "on")
    hass.states.async_set(dock, "auto", {"temperature": 20.0})
    config = _substituted_config(
        "tracker_warm_awake.yaml",
        {
            "wake_time": wake_time,
            "preheat_minutes": 15,
            "warm_temperature": 32.0,
            "warm_duration": {"seconds": 0},
        },
    )
    config.update({"id": "test_warm_awake", "alias": "Test warm awake"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    # The time-pattern listener preserves its setup microseconds; advance one
    # second into the target minute so the scheduled callback is due.
    with patch("homeassistant.util.dt.now", return_value=trigger_time):
        async_fire_time_changed(
            hass, trigger_time + timedelta(seconds=1), fire_all=True
        )
        await hass.async_block_till_done()

    await hass.services.async_call(
        "automation",
        "turn_off",
        {"entity_id": "automation.test_warm_awake"},
        blocking=True,
    )

    assert len(mode_calls) == 1
    assert mode_calls[0].data["hvac_mode"] == "auto"
    assert len(temperature_calls) == 1
    assert temperature_calls[0].data["temperature"] == 32.0
    assert len(off_calls) == 1


async def test_report_alert_blueprint_builds_action_message(
    hass: HomeAssistant,
) -> None:
    """Missed thresholds are rendered into the public action template variable."""
    alert_calls = async_mock_service(hass, "test", "alert")
    states = {
        "sensor.sleepme_last_report": "2026-07-11",
        "sensor.sleepme_score": "60",
        "sensor.sleepme_duration": "21600",
        "sensor.sleepme_efficiency": "75",
        "sensor.sleepme_latency": "2700",
        "sensor.sleepme_deep_sleep": "8",
    }
    for entity_id, state in states.items():
        hass.states.async_set(entity_id, state)
    config = _substituted_config(
        "sleep_report_alert.yaml",
        {
            "evaluation_delay": {"seconds": 0},
            "alert_actions": [
                {
                    "action": "test.alert",
                    "data": {"message": "{{ sleepme_alert_message }}"},
                }
            ],
        },
    )
    config.update({"id": "test_report_alert", "alias": "Test report alert"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    hass.states.async_set("sensor.sleepme_last_report", "2026-07-12")
    await hass.async_block_till_done()

    assert len(alert_calls) == 1
    message = alert_calls[0].data["message"]
    assert "sleep score 60" in message
    assert "sleep duration 6.0 h" in message
    assert "efficiency 75" in message
    assert "latency 45" in message
    assert "deep sleep 8" in message


async def test_report_alert_skips_incomplete_sensor_updates(
    hass: HomeAssistant,
) -> None:
    """Unavailable report metrics never produce a false threshold alert."""
    alert_calls = async_mock_service(hass, "test", "alert")
    states = {
        "sensor.sleepme_last_report": "2026-07-11",
        "sensor.sleepme_score": "unavailable",
        "sensor.sleepme_duration": "unavailable",
        "sensor.sleepme_efficiency": "unavailable",
        "sensor.sleepme_latency": "unavailable",
        "sensor.sleepme_deep_sleep": "unavailable",
    }
    for entity_id, state in states.items():
        hass.states.async_set(entity_id, state)
    config = _substituted_config(
        "sleep_report_alert.yaml",
        {
            "evaluation_delay": {"seconds": 0},
            "alert_actions": [{"action": "test.alert"}],
        },
    )
    config.update({"id": "test_incomplete_report", "alias": "Test incomplete"})
    assert await async_setup_component(hass, "automation", {"automation": [config]})

    hass.states.async_set("sensor.sleepme_last_report", "2026-07-12")
    await hass.async_block_till_done()

    assert not alert_calls


async def test_entity_translations_fall_back_for_every_ha_language(
    hass: HomeAssistant,
) -> None:
    """Every frontend locale resolves every report entity and option string."""
    source_strings = json.loads(STRINGS.read_text())
    entity_names = {
        f"component.{DOMAIN}.entity.sensor.{key}.name": value["name"]
        for key, value in source_strings["entity"]["sensor"].items()
    }
    required_option_keys = {
        f"component.{DOMAIN}.options.step.init.title",
        f"component.{DOMAIN}.options.step.init.description",
        f"component.{DOMAIN}.options.step.init.data.scan_interval",
        f"component.{DOMAIN}.options.step.init.data.sleep_target_hours",
        f"component.{DOMAIN}.options.error.invalid_scan_interval",
        f"component.{DOMAIN}.options.error.invalid_sleep_target",
    }

    for language in LANGUAGES:
        entity_strings = await translation.async_get_translations(
            hass, language, "entity", {DOMAIN}
        )
        assert {key: entity_strings.get(key) for key in entity_names} == entity_names, (
            language
        )

        option_strings = await translation.async_get_translations(
            hass, language, "options", {DOMAIN}
        )
        assert required_option_keys <= option_strings.keys(), language
        assert all(option_strings[key] for key in required_option_keys), language
