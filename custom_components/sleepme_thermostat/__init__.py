"""SleepMe custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import cast

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonArrayType

from .const import (
    API_URL,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS_BACK,
    ATTR_START_DATE,
    ATTR_TIME_ZONE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLEEP_REPORT_DAYS_BACK,
    DEFAULT_SLEEP_REPORT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SLEEP_REPORT_DAYS_BACK,
    SERVICE_GET_SLEEP_REPORTS,
    SLEEP_REPORT_HISTORY_DAYS,
)
from .helpers import is_sleep_tracker
from .sleepme import SleepMeClient
from .sleepme_api import SleepMeAPIError
from .update_manager import SleepMeUpdateManager, SleepReportUpdateManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GET_SLEEP_REPORTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_START_DATE): cv.date,
        vol.Optional(ATTR_DAYS_BACK, default=DEFAULT_SLEEP_REPORT_DAYS_BACK): vol.All(
            vol.Coerce(int),
            vol.Range(min=0, max=MAX_SLEEP_REPORT_DAYS_BACK),
        ),
        vol.Optional(ATTR_TIME_ZONE): cv.string,
    }
)

PLATFORMS = ["climate", "binary_sensor", "sensor"]


@dataclass(slots=True)
class SleepMeData:
    """Per-entry runtime state.

    Held on `entry.runtime_data` (HA 2024.11+); HA manages lifetime so we
    don't manually populate / clear hass.data anymore.
    """

    client: SleepMeClient
    coordinator: SleepMeUpdateManager
    report_coordinator: SleepReportUpdateManager | None
    # Raw fields from entry.data; helpers.build_device_info() maps them into
    # HA's DeviceInfo TypedDict shape at platform-setup time.
    device_info: dict


# Typed alias for downstream platforms to use as the ConfigEntry parameter type.
type SleepMeConfigEntry = ConfigEntry[SleepMeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration-level actions."""

    async def async_get_sleep_reports(call: ServiceCall) -> ServiceResponse:
        """Return the requested raw report window without recorder overhead."""
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError("SleepMe config entry not found")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("SleepMe config entry is not loaded")

        sleepme_entry = cast(SleepMeConfigEntry, entry)
        time_zone = call.data.get(ATTR_TIME_ZONE, hass.config.time_zone)
        zone = dt_util.get_time_zone(time_zone)
        if zone is None:
            raise ServiceValidationError(f"Unknown IANA time zone: {time_zone}")
        start_date: date = call.data.get(ATTR_START_DATE, dt_util.now(zone).date())

        try:
            reports = await sleepme_entry.runtime_data.client.get_sleep_reports(
                start_date=start_date,
                days_back=call.data[ATTR_DAYS_BACK],
                time_zone=time_zone,
            )
        except SleepMeAPIError as err:
            raise HomeAssistantError(
                f"Could not fetch SleepMe sleep reports: {err}"
            ) from err
        except httpx.HTTPError as err:
            raise HomeAssistantError("Could not fetch SleepMe sleep reports") from err
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        return {"reports": cast(JsonArrayType, reports)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SLEEP_REPORTS,
        async_get_sleep_reports,
        schema=GET_SLEEP_REPORTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SleepMeConfigEntry) -> bool:
    """Set up a SleepMe device from a config entry."""
    api_token = entry.data.get("api_token")
    device_id = entry.data.get("device_id")

    if not api_token or not device_id:
        raise ConfigEntryNotReady("API token or device ID missing from entry data")

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    client = SleepMeClient(hass, API_URL, api_token, device_id)
    coordinator = SleepMeUpdateManager(
        hass, API_URL, api_token, device_id, scan_interval=scan_interval
    )

    # First refresh propagates ConfigEntryAuthFailed (-> reauth flow) and
    # ConfigEntryNotReady (-> HA retries setup) without further plumbing.
    await coordinator.async_config_entry_first_refresh()

    model = entry.data.get("model") or coordinator.data["about"].get("model")
    report_coordinator: SleepReportUpdateManager | None = None
    if is_sleep_tracker(model):
        report_coordinator = SleepReportUpdateManager(
            hass,
            API_URL,
            api_token,
            time_zone=hass.config.time_zone,
            history_days=SLEEP_REPORT_HISTORY_DAYS,
            scan_interval=DEFAULT_SLEEP_REPORT_SCAN_INTERVAL,
        )
        await report_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SleepMeData(
        client=client,
        coordinator=coordinator,
        report_coordinator=report_coordinator,
        device_info={
            "firmware_version": entry.data.get("firmware_version"),
            "mac_address": entry.data.get("mac_address"),
            "model": entry.data.get("model"),
            "serial_number": entry.data.get("serial_number"),
        },
    )

    # Reload on options change. async_on_unload registers the unsubscribe so
    # it fires automatically during async_unload_entry.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug(
        "Entry %s set up for device %s (model=%s, fw=%s)",
        entry.entry_id,
        device_id,
        entry.data.get("model"),
        entry.data.get("firmware_version"),
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current schema.

    v3 -> v4: drop `api_url` (always equals API_URL) and `name`.
    v4 -> v5: recognize existing ST501NA entries as Sleep Trackers.
    """
    _LOGGER.debug(
        "Migrating SleepMe entry %s from version %s", entry.entry_id, entry.version
    )

    if entry.version < 4:
        new_data = {k: v for k, v in entry.data.items() if k not in ("api_url", "name")}
        hass.config_entries.async_update_entry(entry, data=new_data, version=4)
        _LOGGER.info(
            "Migrated SleepMe entry %s to schema v4 (dropped api_url, name)",
            entry.entry_id,
        )

    if entry.version < 5:
        new_title = entry.title
        if is_sleep_tracker(entry.data.get("model")) and entry.title.startswith(
            "Dock Pro "
        ):
            new_title = f"Sleep Tracker {entry.title.removeprefix('Dock Pro ')}"
        hass.config_entries.async_update_entry(
            entry,
            title=new_title,
            version=5,
        )
        _LOGGER.info("Migrated SleepMe entry %s to schema v5", entry.entry_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SleepMeConfigEntry) -> bool:
    """Unload a config entry."""
    # HA clears entry.runtime_data automatically on successful unload.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
