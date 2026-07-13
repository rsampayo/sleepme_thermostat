"""Helpers for selecting and summarizing Sleepme sleep reports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.util import dt as dt_util

DURATION_FIELDS = (
    "total_session_duration",
    "in_bed_duration",
    "total_sleep_duration",
    "awake_duration",
    "light_sleep_duration",
    "rem_sleep_duration",
    "deep_sleep_duration",
    "sleep_latency",
)


def latest_sleep_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest report containing at least one completed session."""
    candidates = [
        report
        for report in reports
        if isinstance(report.get("date"), str)
        and isinstance(report.get("sessions"), list)
        and report["sessions"]
    ]
    return max(candidates, key=lambda report: report["date"], default=None)


def summarize_sleep_report(report: dict[str, Any] | None) -> dict[str, Any]:
    """Aggregate all sessions in one daily report for entity-friendly states."""
    if report is None:
        return {}

    sessions = [
        session for session in report.get("sessions", []) if isinstance(session, dict)
    ]
    summary: dict[str, Any] = {
        "date": _parse_date(report.get("date")),
        "sleep_score_percent": report.get("sleep_score_percent"),
        "session_count": len(sessions),
        "hypnogram_segment_count": sum(
            _number(session.get("hypnogram", {}).get("raw_hypnogram_segment_count"))
            for session in sessions
            if isinstance(session.get("hypnogram"), dict)
        ),
    }

    for field in DURATION_FIELDS:
        summary[field] = sum(_number(session.get(field)) for session in sessions)

    enter_times = [
        parsed
        for session in sessions
        if (parsed := _parse_datetime(session.get("enter_bed_time"))) is not None
    ]
    exit_times = [
        parsed
        for session in sessions
        if (parsed := _parse_datetime(session.get("exit_bed_time"))) is not None
    ]
    summary["enter_bed_time"] = min(enter_times, default=None)
    summary["exit_bed_time"] = max(exit_times, default=None)
    return summary


def _number(value: Any) -> int | float:
    """Return numeric API values while treating absent/invalid values as zero."""
    return (
        value if isinstance(value, int | float) and not isinstance(value, bool) else 0
    )


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an RFC3339 timestamp returned by Sleepme."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _parse_date(value: Any) -> date | None:
    """Parse an ISO calendar date returned by Sleepme."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
