"""Sensors for SleepMe climate systems and sleep trackers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SLEEP_TARGET_HOURS,
    DEFAULT_SLEEP_TARGET_HOURS,
    DOMAIN,
)
from .helpers import build_device_info, is_sleep_tracker
from .sleep_reports import (
    latest_sleep_report,
    summarize_sleep_history,
    summarize_sleep_report,
)
from .update_manager import SleepReportUpdateManager

if TYPE_CHECKING:
    from .update_manager import SleepMeUpdateManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SleepMe sensors from a config entry."""
    device_id: str = entry.data["device_id"]
    data = entry.runtime_data
    device_info = build_device_info(device_id, entry.title, data.device_info)

    entities: list[SensorEntity] = [
        IPAddressSensor(data.coordinator, device_id, device_info),
        LANAddressSensor(data.coordinator, device_id, device_info),
        FirmwareVersionSensor(data.coordinator, device_id, device_info),
    ]

    if is_sleep_tracker(entry.data.get("model")):
        entities.extend(
            [
                TrackerEnvironmentHumiditySensor(
                    data.coordinator, device_id, device_info
                ),
                TrackerEnvironmentTemperatureSensor(
                    data.coordinator, device_id, device_info
                ),
                TrackerBedTemperatureSensor(data.coordinator, device_id, device_info),
            ]
        )
        if data.report_coordinator is not None:
            sleep_target_seconds = (
                entry.options.get(CONF_SLEEP_TARGET_HOURS, DEFAULT_SLEEP_TARGET_HOURS)
                * 3600
            )
            entities.extend(
                _build_sleep_report_sensors(
                    data.report_coordinator,
                    device_id,
                    device_info,
                    sleep_target_seconds=sleep_target_seconds,
                )
            )
    else:
        entities.extend(
            [
                BrightnessLevelSensor(data.coordinator, device_id, device_info),
                DisplayTemperatureUnitSensor(data.coordinator, device_id, device_info),
                TimeZoneSensor(data.coordinator, device_id, device_info),
                WaterLevelSensor(data.coordinator, device_id, device_info),
            ]
        )

    async_add_entities(entities)


class _SleepMeDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Common base for diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
        *,
        suffix: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_name = label
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{suffix}"
        self._attr_device_info = device_info


class IPAddressSensor(_SleepMeDiagnosticSensor):
    """IP address of the device."""

    _attr_icon = "mdi:ip"

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="ip_address",
            label="IP Address",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["about"].get("ip_address")


class LANAddressSensor(_SleepMeDiagnosticSensor):
    """LAN address of the device."""

    _attr_icon = "mdi:lan"

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="lan_address",
            label="LAN Address",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["about"].get("lan_address")


class BrightnessLevelSensor(_SleepMeDiagnosticSensor):
    """Display brightness in percent."""

    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="brightness_level",
            label="Brightness Level",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["control"].get("brightness_level")


class DisplayTemperatureUnitSensor(_SleepMeDiagnosticSensor):
    """Display temperature unit (C / F)."""

    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="display_temperature_unit",
            label="Display Temperature Unit",
        )

    @property
    def native_value(self) -> str | int | None:
        unit = self.coordinator.data["control"].get("display_temperature_unit")
        return unit.upper() if unit else None


class TimeZoneSensor(_SleepMeDiagnosticSensor):
    """Configured time zone."""

    _attr_icon = "mdi:earth"

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="time_zone",
            label="Time Zone",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["control"].get("time_zone")


class WaterLevelSensor(_SleepMeDiagnosticSensor):
    """Continuous water-level percent (not the boolean low-level alert)."""

    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="water_level",
            label="Water Level",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["status"].get("water_level")


class FirmwareVersionSensor(_SleepMeDiagnosticSensor):
    """Reports the current device firmware version. Useful for update notifications."""

    _attr_icon = "mdi:chip"

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="firmware_version",
            label="Firmware Version",
        )

    @property
    def native_value(self) -> str | int | None:
        return self.coordinator.data["about"].get("firmware_version")


class _SleepMeTrackerSensor(CoordinatorEntity, SensorEntity):
    """Base for live, non-diagnostic tracker measurements."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
        *,
        suffix: str,
        label: str,
        status_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._status_key = status_key
        self._attr_name = label
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{suffix}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int | float | None:
        """Return the live tracker status value."""
        return self.coordinator.data["status"].get(self._status_key)


class TrackerEnvironmentHumiditySensor(_SleepMeTrackerSensor):
    """Current room humidity measured by the tracker hub."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="environment_humidity",
            label="Environment Humidity",
            status_key="environment_humidity",
        )


class TrackerEnvironmentTemperatureSensor(_SleepMeTrackerSensor):
    """Current room temperature measured by the tracker hub."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="environment_temperature",
            label="Environment Temperature",
            status_key="environment_temperature_c",
        )


class TrackerBedTemperatureSensor(_SleepMeTrackerSensor):
    """Current in-bed temperature measured by the tracker pad."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: SleepMeUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device_info,
            suffix="bed_temperature",
            label="Bed Temperature",
            status_key="bed_temperature_c",
        )


class SleepReportSensor(CoordinatorEntity[SleepReportUpdateManager], SensorEntity):
    """One aggregate field from the latest completed daily sleep report."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SleepReportUpdateManager,
        device_id: str,
        device_info: DeviceInfo,
        *,
        key: str,
        label: str,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
        scope: Literal["latest", "history"] = "latest",
        sleep_target_seconds: float = DEFAULT_SLEEP_TARGET_HOURS * 3600,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        # Keep the English label beside the entity definition for maintainers,
        # while HA resolves the displayed name through strings.json and the
        # active frontend language (falling back to English when untranslated).
        self._english_label = label
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{device_id}_sleep_report_{key}"
        self._attr_device_info = device_info
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._scope = scope
        self._sleep_target_seconds = sleep_target_seconds
        self._attr_entity_registry_enabled_default = enabled_default

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the latest report summary value for this sensor."""
        if self._scope == "history":
            return summarize_sleep_history(
                self.coordinator.data or [],
                sleep_target_seconds=self._sleep_target_seconds,
            ).get(self._key)
        report = latest_sleep_report(self.coordinator.data or [])
        return summarize_sleep_report(
            report, sleep_target_seconds=self._sleep_target_seconds
        ).get(self._key)


def _build_sleep_report_sensors(
    coordinator: SleepReportUpdateManager,
    device_id: str,
    device_info: DeviceInfo,
    *,
    sleep_target_seconds: float,
) -> list[SleepReportSensor]:
    """Build direct and derived sensors backed by public report data."""
    definitions: list[dict[str, Any]] = [
        {
            "key": "date",
            "label": "Last Sleep Report",
            "device_class": SensorDeviceClass.DATE,
        },
        {
            "key": "sleep_score_percent",
            "label": "Sleep Score",
            "unit": PERCENTAGE,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:sleep",
        },
        {
            "key": "session_count",
            "label": "Sleep Sessions",
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:counter",
        },
        {
            "key": "enter_bed_time",
            "label": "Entered Bed",
            "device_class": SensorDeviceClass.TIMESTAMP,
        },
        {
            "key": "exit_bed_time",
            "label": "Exited Bed",
            "device_class": SensorDeviceClass.TIMESTAMP,
        },
    ]
    duration_labels = {
        "total_session_duration": "Total Session Duration",
        "in_bed_duration": "In-bed Duration",
        "total_sleep_duration": "Total Sleep Duration",
        "awake_duration": "Awake Duration",
        "light_sleep_duration": "Light Sleep Duration",
        "rem_sleep_duration": "REM Sleep Duration",
        "deep_sleep_duration": "Deep Sleep Duration",
        "sleep_latency": "Sleep Latency",
    }
    definitions.extend(
        {
            "key": key,
            "label": label,
            "device_class": SensorDeviceClass.DURATION,
            "unit": UnitOfTime.SECONDS,
            "state_class": SensorStateClass.MEASUREMENT,
        }
        for key, label in duration_labels.items()
    )
    definitions.append(
        {
            "key": "hypnogram_segment_count",
            "label": "Hypnogram Segments",
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:chart-timeline-variant",
        }
    )
    definitions.extend(
        [
            {
                "key": "sleep_efficiency_percent",
                "label": "Sleep Efficiency",
                "unit": PERCENTAGE,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:percent-circle-outline",
            },
            {
                "key": "wake_after_sleep_onset",
                "label": "Wake After Sleep Onset",
                "device_class": SensorDeviceClass.DURATION,
                "unit": UnitOfTime.SECONDS,
                "state_class": SensorStateClass.MEASUREMENT,
            },
            {
                "key": "restorative_sleep_duration",
                "label": "Restorative Sleep Duration",
                "device_class": SensorDeviceClass.DURATION,
                "unit": UnitOfTime.SECONDS,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:brain",
            },
            {
                "key": "sleep_debt",
                "label": "Sleep Debt",
                "device_class": SensorDeviceClass.DURATION,
                "unit": UnitOfTime.SECONDS,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:bed-clock",
            },
            {
                "key": "sleep_goal_percent",
                "label": "Sleep Goal",
                "unit": PERCENTAGE,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:target",
            },
            {
                "key": "awakening_count",
                "label": "Awakenings",
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:weather-sunset-up",
            },
            {
                "key": "longest_uninterrupted_sleep_duration",
                "label": "Longest Uninterrupted Sleep",
                "device_class": SensorDeviceClass.DURATION,
                "unit": UnitOfTime.SECONDS,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:sleep",
            },
            {
                "key": "main_enter_bed_time",
                "label": "Main Sleep Entered Bed",
                "device_class": SensorDeviceClass.TIMESTAMP,
            },
            {
                "key": "main_exit_bed_time",
                "label": "Main Sleep Exited Bed",
                "device_class": SensorDeviceClass.TIMESTAMP,
            },
            {
                "key": "sleep_midpoint",
                "label": "Sleep Midpoint",
                "device_class": SensorDeviceClass.TIMESTAMP,
                "icon": "mdi:clock-time-four-outline",
            },
            {
                "key": "nap_count",
                "label": "Additional Sleep Sessions",
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:bed-clock",
            },
            {
                "key": "nap_sleep_duration",
                "label": "Additional Sleep Duration",
                "device_class": SensorDeviceClass.DURATION,
                "unit": UnitOfTime.SECONDS,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:bed-clock",
            },
        ]
    )
    for key, label in (
        ("awake_percent", "Awake"),
        ("light_sleep_percent", "Light Sleep"),
        ("rem_sleep_percent", "REM Sleep"),
        ("deep_sleep_percent", "Deep Sleep"),
        ("restorative_sleep_percent", "Restorative Sleep"),
    ):
        definitions.append(
            {
                "key": key,
                "label": f"{label} Percentage",
                "unit": PERCENTAGE,
                "state_class": SensorStateClass.MEASUREMENT,
                "icon": "mdi:chart-donut",
            }
        )

    history_definitions: list[dict[str, Any]] = []
    for days in (7, 30):
        suffix = f"_{days}d"
        history_definitions.extend(
            [
                {
                    "key": f"tracked_nights{suffix}",
                    "label": f"Tracked Nights {days} Day",
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:calendar-check",
                },
                {
                    "key": f"average_sleep_score_percent{suffix}",
                    "label": f"Average Sleep Score {days} Day",
                    "unit": PERCENTAGE,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:sleep",
                },
                {
                    "key": f"average_total_sleep_duration{suffix}",
                    "label": f"Average Sleep Duration {days} Day",
                    "device_class": SensorDeviceClass.DURATION,
                    "unit": UnitOfTime.SECONDS,
                    "state_class": SensorStateClass.MEASUREMENT,
                },
                {
                    "key": f"average_sleep_efficiency_percent{suffix}",
                    "label": f"Average Sleep Efficiency {days} Day",
                    "unit": PERCENTAGE,
                    "state_class": SensorStateClass.MEASUREMENT,
                },
                {
                    "key": f"average_sleep_latency{suffix}",
                    "label": f"Average Sleep Latency {days} Day",
                    "device_class": SensorDeviceClass.DURATION,
                    "unit": UnitOfTime.SECONDS,
                    "state_class": SensorStateClass.MEASUREMENT,
                },
                {
                    "key": f"average_deep_sleep_percent{suffix}",
                    "label": f"Average Deep Sleep {days} Day",
                    "unit": PERCENTAGE,
                    "state_class": SensorStateClass.MEASUREMENT,
                },
                {
                    "key": f"average_rem_sleep_percent{suffix}",
                    "label": f"Average REM Sleep {days} Day",
                    "unit": PERCENTAGE,
                    "state_class": SensorStateClass.MEASUREMENT,
                },
                {
                    "key": f"average_awakening_count{suffix}",
                    "label": f"Average Awakenings {days} Day",
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:weather-sunset-up",
                },
                {
                    "key": f"cumulative_sleep_debt{suffix}",
                    "label": f"Cumulative Sleep Debt {days} Day",
                    "device_class": SensorDeviceClass.DURATION,
                    "unit": UnitOfTime.SECONDS,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:bed-clock",
                },
                {
                    "key": f"bedtime_consistency{suffix}",
                    "label": f"Bedtime Consistency {days} Day",
                    "device_class": SensorDeviceClass.DURATION,
                    "unit": UnitOfTime.MINUTES,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:clock-check-outline",
                },
                {
                    "key": f"wake_time_consistency{suffix}",
                    "label": f"Wake Time Consistency {days} Day",
                    "device_class": SensorDeviceClass.DURATION,
                    "unit": UnitOfTime.MINUTES,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "icon": "mdi:clock-check-outline",
                },
            ]
        )
    return [
        SleepReportSensor(
            coordinator,
            device_id,
            device_info,
            sleep_target_seconds=sleep_target_seconds,
            **definition,
        )
        for definition in definitions
    ] + [
        SleepReportSensor(
            coordinator,
            device_id,
            device_info,
            scope="history",
            sleep_target_seconds=sleep_target_seconds,
            **definition,
        )
        for definition in history_definitions
    ]
