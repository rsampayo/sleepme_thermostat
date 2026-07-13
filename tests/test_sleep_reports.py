"""Tests for sleep-report selection and daily-session aggregation."""

from __future__ import annotations

from datetime import date, datetime

from custom_components.sleepme_thermostat.sleep_reports import (
    latest_sleep_report,
    summarize_sleep_report,
)


def test_latest_report_skips_empty_current_day(sleep_reports: list[dict]) -> None:
    """An empty report for today does not hide the latest completed night."""
    report = latest_sleep_report(sleep_reports)
    assert report is not None
    assert report["date"] == "2026-07-12"


def test_summary_aggregates_every_session(sleep_reports: list[dict]) -> None:
    """Naps and the main sleep session are represented in daily totals."""
    summary = summarize_sleep_report(latest_sleep_report(sleep_reports))

    assert summary["date"] == date(2026, 7, 12)
    assert summary["sleep_score_percent"] == 88
    assert summary["session_count"] == 2
    assert summary["total_session_duration"] == 36000
    assert summary["in_bed_duration"] == 35000
    assert summary["total_sleep_duration"] == 31200
    assert summary["awake_duration"] == 3800
    assert summary["light_sleep_duration"] == 15600
    assert summary["rem_sleep_duration"] == 7800
    assert summary["deep_sleep_duration"] == 7800
    assert summary["sleep_latency"] == 1400
    assert summary["hypnogram_segment_count"] == 7
    assert summary["enter_bed_time"] == datetime.fromisoformat(
        "2026-07-12T14:00:00+02:00"
    )
    assert summary["exit_bed_time"] == datetime.fromisoformat(
        "2026-07-13T07:00:00+02:00"
    )


def test_missing_report_returns_empty_summary() -> None:
    assert latest_sleep_report([]) is None
    assert summarize_sleep_report(None) == {}
