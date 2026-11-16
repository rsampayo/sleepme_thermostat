"""Setup/unload/multi-entry smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.sleepme_thermostat.const import API_URL, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry
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


async def test_migrate_entry_v3_to_v4(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """A v3 entry auto-migrates to v4: api_url and name removed; version bumps."""
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
    assert entry.version == 4
    assert "api_url" not in entry.data
    assert "name" not in entry.data
    # Other keys survive untouched.
    assert entry.data["device_id"] == MOCK_DEVICE_ID
    assert entry.data["api_token"] == MOCK_API_TOKEN
    assert entry.title == f"Dock Pro {MOCK_NAME}"
