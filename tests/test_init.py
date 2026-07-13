"""Setup/unload/multi-entry smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.sleepme_thermostat.const import API_URL, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN, MOCK_DEVICE_ID, MOCK_NAME


def _make_entry(
    *,
    entry_id: str = "entry_main",
    device_id: str = MOCK_DEVICE_ID,
    title_suffix: str = MOCK_NAME,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        version=3,
        unique_id=device_id,
        title=f"Dock Pro {title_suffix}",
        data={
            "api_url": API_URL,
            "api_token": MOCK_API_TOKEN,
            "device_id": device_id,
            "name": title_suffix,
            "firmware_version": "0.0.0-test",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "TEST-SERIAL",
        },
    )


async def test_setup_entry_loads(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """async_setup_entry returns True and entry reaches LOADED."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert entry.runtime_data.coordinator is not None
    assert entry.runtime_data.report_coordinator is None


async def test_tracker_entry_loads_all_live_and_report_entities(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
) -> None:
    """ST501NA gets tracker entities, report entities, and no climate entity."""
    # German is intentionally not bundled: HA must resolve the English source
    # fallback, proving unsupported integration locales remain fully usable.
    hass.config.language = "de"
    mock_sleepme_client.get_device_status.return_value = tracker_status
    device_id = "tracker-device"
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_tracker",
        version=5,
        unique_id=device_id,
        title="Sleep Tracker Bedroom",
        data={
            "api_token": MOCK_API_TOKEN,
            "device_id": device_id,
            "firmware_version": "2.3.4-test",
            "mac_address": "11:22:33:44:55:66",
            "model": "ST501NA",
            "serial_number": "TRACKER-TEST-SERIAL",
        },
        options={"sleep_target_hours": 10.0},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.report_coordinator is not None
    assert entry.runtime_data.report_coordinator.last_update_success is True

    registry = er.async_get(hass)

    def state_for(platform: str, unique_suffix: str):
        entity_id = registry.async_get_entity_id(
            platform,
            DOMAIN,
            f"{DOMAIN}_{device_id}_{unique_suffix}",
        )
        assert entity_id is not None
        state = hass.states.get(entity_id)
        assert state is not None
        return state

    assert state_for("binary_sensor", "connected").state == "on"
    assert state_for("binary_sensor", "user_detected").state == "on"
    assert state_for("sensor", "environment_humidity").state == "47.5"
    assert state_for("sensor", "environment_temperature").state == "21.5"
    assert state_for("sensor", "bed_temperature").state == "28.0"
    assert state_for("sensor", "sleep_report_date").state == "2026-07-12"
    assert state_for("sensor", "sleep_report_sleep_score_percent").state == "88"
    assert state_for("sensor", "sleep_report_session_count").state == "2"
    assert state_for("sensor", "sleep_report_total_sleep_duration").state == "31200"
    assert state_for("sensor", "sleep_report_hypnogram_segment_count").state == "7"
    assert state_for("sensor", "sleep_report_sleep_efficiency_percent").state == (
        "89.1"
    )
    assert state_for("sensor", "sleep_report_wake_after_sleep_onset").state == "2400"
    assert state_for("sensor", "sleep_report_deep_sleep_percent").state == "25.0"
    assert state_for("sensor", "sleep_report_awakening_count").state == "0"
    assert (
        state_for("sensor", "sleep_report_longest_uninterrupted_sleep_duration").state
        == "27900"
    )
    assert state_for("sensor", "sleep_report_nap_count").state == "1"
    assert state_for("sensor", "sleep_report_sleep_debt").state == "4800.0"
    assert state_for("sensor", "sleep_report_sleep_goal_percent").state == "86.7"
    assert state_for("sensor", "sleep_report_tracked_nights_7d").state == "2"
    assert (
        state_for("sensor", "sleep_report_average_sleep_score_percent_30d").state
        == "84.0"
    )
    assert state_for("sensor", "sleep_report_bedtime_consistency_7d").state == ("15.0")
    assert (
        state_for("sensor", "sleep_report_sleep_efficiency_percent").attributes[
            "friendly_name"
        ]
        == "Sleep Tracker Bedroom Sleep Efficiency"
    )

    assert (
        registry.async_get_entity_id(
            "climate",
            DOMAIN,
            f"{DOMAIN}_{device_id}_thermostat",
        )
        is None
    )


async def test_unload_entry(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Entry unloads cleanly; data is cleared; no lingering timers."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # runtime_data is automatically detached by HA on unload.


async def test_multi_entry_isolation(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Two entries co-exist with distinct hass.data keys; unloading one leaves the other loaded."""
    entry_a = _make_entry(
        entry_id="entry_a", device_id="device_a", title_suffix="Ramon"
    )
    entry_b = _make_entry(
        entry_id="entry_b", device_id="device_b", title_suffix="Chiva"
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    # Setting up the component drives setup of all registered entries.
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    # Phase 6: runtime_data replaces hass.data[DOMAIN][entry.entry_id].
    assert entry_a.runtime_data is not None
    assert entry_b.runtime_data is not None
    # Distinct coordinator instances per entry.
    assert entry_a.runtime_data.coordinator is not entry_b.runtime_data.coordinator

    # Unload one; the other survives.
    assert await hass.config_entries.async_unload(entry_a.entry_id)
    await hass.async_block_till_done()
    assert entry_a.state is ConfigEntryState.NOT_LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    # entry_b still has runtime_data.
    assert entry_b.runtime_data is not None


async def test_migrate_entry_v3_to_v5(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """A v3 entry reaches v5 with obsolete fields removed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_v3",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": MOCK_API_TOKEN,
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "0.0.0-test",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "TEST-SERIAL",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 5
    assert "api_url" not in entry.data
    assert "name" not in entry.data
    # Other keys survive untouched.
    assert entry.data["device_id"] == MOCK_DEVICE_ID
    assert entry.data["api_token"] == MOCK_API_TOKEN
    assert entry.title == f"Dock Pro {MOCK_NAME}"


async def test_migrate_tracker_entry_retitles_device(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
) -> None:
    """A tracker configured before v5 loses the misleading Dock Pro title."""
    mock_sleepme_client.get_device_status.return_value = tracker_status
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_old_tracker",
        version=4,
        unique_id="tracker-device",
        title="Dock Pro Bedroom",
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

    assert entry.version == 5
    assert entry.title == "Sleep Tracker Bedroom"
