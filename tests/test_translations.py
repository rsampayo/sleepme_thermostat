"""Translation completeness: every language and every entity name stays in step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from custom_components.sleepme_thermostat.sensor import _build_sleep_report_sensors

INTEGRATION = Path(__file__).parent.parent / "custom_components" / "sleepme_thermostat"
STRINGS = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
LANGUAGES = sorted(path.stem for path in (INTEGRATION / "translations").glob("*.json"))


def _flatten(data: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            keys |= _flatten(value, f"{prefix}{key}.")
        else:
            keys.add(f"{prefix}{key}")
    return keys


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_has_every_key(language: str) -> None:
    """CI only diffs strings.json against en.json; this covers the rest."""
    translation = json.loads(
        (INTEGRATION / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )

    assert _flatten(translation) == _flatten(STRINGS)


def test_report_sensor_labels_match_the_english_strings() -> None:
    """The label beside each definition is documentation; keep it truthful."""
    sensors = _build_sleep_report_sensors(MagicMock(), "device", MagicMock())
    names = STRINGS["entity"]["sensor"]

    assert len(sensors) == 53
    for sensor in sensors:
        assert sensor.translation_key in names
    assert {
        definition_key: label
        for definition_key, label in _REPORT_LABELS.items()
        if names[definition_key]["name"] != label
    } == {}


def _collect_report_labels() -> dict[str, str]:
    """Capture the `label` each report sensor definition was built with."""
    from custom_components.sleepme_thermostat import sensor as sensor_module

    captured: dict[str, str] = {}
    original_init = sensor_module.SleepReportSensor.__init__

    def recording_init(self, *args: Any, **kwargs: Any) -> None:
        captured[kwargs["key"]] = kwargs["label"]
        original_init(self, *args, **kwargs)

    sensor_module.SleepReportSensor.__init__ = recording_init  # type: ignore[method-assign]
    try:
        _build_sleep_report_sensors(MagicMock(), "device", MagicMock())
    finally:
        sensor_module.SleepReportSensor.__init__ = original_init  # type: ignore[method-assign]
    return captured


_REPORT_LABELS = _collect_report_labels()
