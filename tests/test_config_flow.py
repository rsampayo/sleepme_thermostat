"""Config flow tests: happy path, invalid token, reauth."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.sleepme_thermostat.const import (
    API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SLEEP_TARGET_HOURS,
    DOMAIN,
)
from custom_components.sleepme_thermostat.sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import MOCK_API_TOKEN, MOCK_DEVICE_ID, MOCK_NAME


@pytest.fixture
def mock_flow_client():
    """Patch the SleepMeClient used by config_flow."""
    with patch(
        "custom_components.sleepme_thermostat.config_flow.SleepMeClient",
        autospec=True,
    ) as mock_cls:
        instance = mock_cls.return_value
        instance.get_claimed_devices = AsyncMock(
            return_value=[{"id": MOCK_DEVICE_ID, "name": MOCK_NAME}]
        )
        instance.get_device_status = AsyncMock(
            return_value={
                "about": {
                    "firmware_version": "1.0",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                    "model": "Dock Pro",
                    "serial_number": "SN-1",
                }
            }
        )
        yield instance


async def test_happy_path(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """User flow reaches CREATE_ENTRY with expected data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": MOCK_API_TOKEN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": MOCK_DEVICE_ID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Dock Pro {MOCK_NAME}"
    assert result["data"]["api_token"] == MOCK_API_TOKEN
    assert result["data"]["device_id"] == MOCK_DEVICE_ID
    assert result["data"]["model"] == "Dock Pro"


async def test_select_device_accepts_gen2(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Gen-2 ('x2-') devices now configure like any other once the v1 API
    serves them. See issue #46."""
    gen2_id = "x2-d8fe1o7aq7uc73jgee8g"
    mock_flow_client.get_claimed_devices.return_value = [
        {"id": gen2_id, "name": "Chilipad 2.0"}
    ]
    mock_flow_client.get_device_status.return_value = {
        "about": {
            "firmware_version": "1.11.1339",
            "mac_address": "ee:ee:ee:ee:ee:ee",
            "model": "DP723NA",
            "serial_number": "12345600290",
        }
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": MOCK_API_TOKEN}
    )
    assert result["step_id"] == "select_device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": gen2_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dock Pro Chilipad 2.0"
    assert result["data"]["device_id"] == gen2_id
    assert result["data"]["model"] == "DP723NA"
    mock_flow_client.get_device_status.assert_called_once()


async def test_select_device_recognizes_sleep_tracker(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """ST501NA is configured as a Sleep Tracker instead of a Dock Pro."""
    tracker_id = "st-tracker-device"
    mock_flow_client.get_claimed_devices.return_value = [
        {"id": tracker_id, "name": "Bedroom"}
    ]
    mock_flow_client.get_device_status.return_value = {
        "about": {
            "firmware_version": "2.3.4",
            "mac_address": "11:22:33:44:55:66",
            "model": "ST501NA",
            "serial_number": "TRACKER-1",
        }
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": MOCK_API_TOKEN}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": tracker_id}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sleep Tracker Bedroom"
    assert result["data"]["model"] == "ST501NA"


async def test_user_step_invalid_token(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """SleepMeAuthError on the user step surfaces as errors['base']='invalid_token'."""
    mock_flow_client.get_claimed_devices.side_effect = SleepMeAuthError("403")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": "bad-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_token"}


async def test_user_step_cannot_connect(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Connection failure surfaces as errors['base']='cannot_connect'."""
    mock_flow_client.get_claimed_devices.side_effect = SleepMeConnectionError("dns")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": MOCK_API_TOKEN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Reauth: existing entry, new token validated, entry updated and aborted as success."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_reauth",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": "old-token",
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "1.0",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "SN-1",
        },
    )
    entry.add_to_hass(hass)

    # Start the reauth flow as if HA's framework triggered it.
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    # Submit a new token; mock_flow_client.get_claimed_devices returns the same device_id.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_token"] == "new-token"


async def test_reauth_token_for_other_account(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Token that doesn't have access to the configured device_id is rejected."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_other_acct",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": "old-token",
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "1.0",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "SN-1",
        },
    )
    entry.add_to_hass(hass)

    # New token returns a *different* device list — doesn't include our device_id.
    mock_flow_client.get_claimed_devices.return_value = [
        {"id": "other-device", "name": "Other"}
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": "different-account-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "device_not_found_for_token"}
    assert entry.data["api_token"] == "old-token"  # unchanged


async def test_reauth_invalid_token(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """SleepMeAuthError on the reauth step surfaces as invalid_token."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_invalid",
        version=3,
        unique_id=MOCK_DEVICE_ID,
        title=f"Dock Pro {MOCK_NAME}",
        data={
            "api_url": API_URL,
            "api_token": "old-token",
            "device_id": MOCK_DEVICE_ID,
            "name": MOCK_NAME,
            "firmware_version": "1.0",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "model": "Dock Pro",
            "serial_number": "SN-1",
        },
    )
    entry.add_to_hass(hass)

    mock_flow_client.get_claimed_devices.side_effect = SleepMeAuthError("403")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_token": "still-bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_token"}


def _entry_with_default_options() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_opts",
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


def _tracker_entry_with_default_options() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_tracker_opts",
        version=5,
        unique_id="tracker-options-device",
        title="Sleep Tracker Bedroom",
        data={
            "api_token": MOCK_API_TOKEN,
            "device_id": "tracker-options-device",
            "firmware_version": "2.3.4",
            "mac_address": "11:22:33:44:55:66",
            "model": "ST501NA",
            "serial_number": "TRACKER-OPTIONS",
        },
    )


async def test_options_flow_happy_path(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Submitting a valid scan_interval persists in entry.options and reloads."""
    entry = _entry_with_default_options()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Open the options flow.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    # Submit a valid interval.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 60

    await hass.async_block_till_done()
    # Entry was reloaded; new coordinator has the new interval.
    coordinator = entry.runtime_data.coordinator
    assert coordinator.update_interval.total_seconds() == 60


async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, mock_sleepme_client: AsyncMock
) -> None:
    """Out-of-range values surface as a form error and are not persisted."""
    entry = _entry_with_default_options()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Too low.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 5}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}
    assert CONF_SCAN_INTERVAL not in entry.options

    # Too high — start a new flow, separate from the previous (still-open) one.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 301}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}


async def test_tracker_options_include_sleep_target(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
) -> None:
    """Tracker options persist the goal used for derived sleep-debt sensors."""
    mock_sleepme_client.get_device_status.return_value = tracker_status
    entry = _tracker_entry_with_default_options()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_SLEEP_TARGET_HOURS: 7.5},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SLEEP_TARGET_HOURS] == 7.5


async def test_tracker_options_reject_invalid_sleep_target(
    hass: HomeAssistant,
    mock_sleepme_client: AsyncMock,
    tracker_status: dict,
) -> None:
    """The configurable target is bounded to a plausible 4-12 hours."""
    mock_sleepme_client.get_device_status.return_value = tracker_status
    entry = _tracker_entry_with_default_options()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_SLEEP_TARGET_HOURS: 3.75},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SLEEP_TARGET_HOURS: "invalid_sleep_target"}
    assert CONF_SLEEP_TARGET_HOURS not in entry.options
