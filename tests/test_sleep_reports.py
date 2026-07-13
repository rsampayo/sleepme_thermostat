"""Tests for sleep-report selection and daily-session aggregation."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from custom_components.sleepme_thermostat.sleep_reports import (
    latest_sleep_report,
    summarize_sleep_history,
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
    assert summary["sleep_efficiency_percent"] == 89.1
    assert summary["wake_after_sleep_onset"] == 2400
    assert summary["awake_percent"] == 10.9
    assert summary["light_sleep_percent"] == 50.0
    assert summary["rem_sleep_percent"] == 25.0
    assert summary["deep_sleep_percent"] == 25.0
    assert summary["restorative_sleep_duration"] == 15600
    assert summary["restorative_sleep_percent"] == 50.0
    assert summary["sleep_debt"] == 0
    assert summary["sleep_goal_percent"] == 108.3
    assert summary["awakening_count"] == 0
    assert summary["longest_uninterrupted_sleep_duration"] == 27900
    assert summary["main_enter_bed_time"] == datetime.fromisoformat(
        "2026-07-12T23:00:00+02:00"
    )
    assert summary["main_exit_bed_time"] == datetime.fromisoformat(
        "2026-07-13T07:00:00+02:00"
    )
    assert summary["sleep_midpoint"] == datetime.fromisoformat(
        "2026-07-13T03:00:00+02:00"
    )
    assert summary["nap_count"] == 1
    assert summary["nap_sleep_duration"] == 6000


def test_summary_uses_configurable_sleep_target(
    sleep_reports: list[dict],
) -> None:
    """Debt and goal percentage reflect HA's option, not a vendor claim."""
    summary = summarize_sleep_report(
        latest_sleep_report(sleep_reports), sleep_target_seconds=10 * 3600
    )

    assert summary["sleep_debt"] == 4800
    assert summary["sleep_goal_percent"] == 86.7


def test_history_summarizes_seven_and_thirty_days(
    sleep_reports: list[dict],
) -> None:
    """Rolling metrics include completed nights and skip today's empty shell."""
    history = summarize_sleep_history(sleep_reports)

    for suffix in ("7d", "30d"):
        assert history[f"tracked_nights_{suffix}"] == 2
        assert history[f"average_sleep_score_percent_{suffix}"] == 84.0
        assert history[f"average_total_sleep_duration_{suffix}"] == 28200.0
        assert history[f"average_sleep_efficiency_percent_{suffix}"] == 89.2
        assert history[f"average_sleep_latency_{suffix}"] == 1150.0
        assert history[f"average_deep_sleep_percent_{suffix}"] == 25.0
        assert history[f"average_rem_sleep_percent_{suffix}"] == 25.0
        assert history[f"average_awakening_count_{suffix}"] == 0.0
        assert history[f"cumulative_sleep_debt_{suffix}"] == 3600
        assert history[f"bedtime_consistency_{suffix}"] == 15.0
        assert history[f"wake_time_consistency_{suffix}"] == 15.0


def test_hypnogram_derives_awakenings_and_longest_run() -> None:
    """Only actual sleep-to-awake transitions split uninterrupted sleep."""
    report = {
        "date": "2026-07-12",
        "sessions": [
            {
                "total_sleep_duration": 300,
                "in_bed_duration": 450,
                "awake_duration": 150,
                "sleep_latency": 50,
                "hypnogram": {
                    "raw_hypnogram_segment_count": 6,
                    "segments": [
                        {"start": 0, "end": 50, "stage": "AWAKE"},
                        {"start": 50, "end": 150, "stage": "LIGHT_SLEEP"},
                        {"start": 150, "end": 250, "stage": "REM_SLEEP"},
                        {"start": 250, "end": 300, "stage": "AWAKE"},
                        {"start": 300, "end": 400, "stage": "DEEP_SLEEP"},
                        {"start": 450, "end": 440, "stage": "AWAKE"},
                    ],
                },
            }
        ],
    }

    summary = summarize_sleep_report(report)
    assert summary["awakening_count"] == 1
    assert summary["longest_uninterrupted_sleep_duration"] == 200


def test_undefined_percentages_and_malformed_shapes_are_safe() -> None:
    """Partial API payloads never cause divide-by-zero or shape failures."""
    summary = summarize_sleep_report(
        {
            "date": "not-a-date",
            "sessions": [{"hypnogram": {"segments": "not-a-list"}}, "bad"],
        }
    )

    assert summary["date"] is None
    assert summary["session_count"] == 1
    assert summary["sleep_efficiency_percent"] is None
    assert summary["sleep_goal_percent"] == 0.0
    assert summary["awakening_count"] == 0
    assert summarize_sleep_history([{"date": "not-a-date"}]) == {}


def test_clock_consistency_wraps_across_midnight() -> None:
    """23:50 and 00:10 are ten minutes from their circular mean."""
    reports = [
        {
            "date": f"2026-07-{day:02d}",
            "sessions": [
                {
                    "enter_bed_time": entered,
                    "exit_bed_time": exited,
                    "total_sleep_duration": 3600,
                }
            ],
        }
        for day, entered, exited in (
            (10, "2026-07-09T23:50:00+00:00", "2026-07-10T07:50:00+00:00"),
            (11, "2026-07-11T00:10:00+00:00", "2026-07-11T08:10:00+00:00"),
        )
    ]

    history = summarize_sleep_history(reports)
    assert history["bedtime_consistency_7d"] == pytest.approx(10.0)
    assert history["wake_time_consistency_7d"] == pytest.approx(10.0)


def test_missing_report_returns_empty_summary() -> None:
    assert latest_sleep_report([]) is None
    assert summarize_sleep_report(None) == {}
