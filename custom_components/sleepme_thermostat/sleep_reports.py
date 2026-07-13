"""Select, aggregate, and derive metrics from Sleepme sleep reports."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DEFAULT_SLEEP_TARGET_HOURS

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

SLEEP_STAGES = frozenset({"LIGHT_SLEEP", "REM_SLEEP", "DEEP_SLEEP"})
SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = 24 * 60 * 60


def latest_sleep_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest valid report containing a completed session."""
    candidates = _dated_completed_reports(reports)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def summarize_sleep_report(
    report: dict[str, Any] | None,
    *,
    sleep_target_seconds: float = DEFAULT_SLEEP_TARGET_HOURS * 3600,
) -> dict[str, Any]:
    """Aggregate sessions and derive recorder-friendly metrics for one day."""
    if report is None:
        return {}

    sessions = _sessions(report)
    summary: dict[str, Any] = {
        "date": _parse_date(report.get("date")),
        "sleep_score_percent": _optional_number(report.get("sleep_score_percent")),
        "session_count": len(sessions),
        "hypnogram_segment_count": sum(
            _number(session.get("hypnogram", {}).get("raw_hypnogram_segment_count"))
            for session in sessions
            if isinstance(session.get("hypnogram"), dict)
        ),
    }

    # Sleepme's public report payload expresses every duration and hypnogram
    # offset in minutes. Normalize once at the boundary so HA duration entities,
    # history, goal/debt calculations, and automations consistently use seconds.
    for field in DURATION_FIELDS:
        summary[field] = sum(
            _minutes_to_seconds(session.get(field)) for session in sessions
        )

    enter_times = _session_datetimes(sessions, "enter_bed_time")
    exit_times = _session_datetimes(sessions, "exit_bed_time")
    summary["enter_bed_time"] = min(enter_times, default=None)
    summary["exit_bed_time"] = max(exit_times, default=None)

    total_sleep = summary["total_sleep_duration"]
    in_bed = summary["in_bed_duration"]
    awake = summary["awake_duration"]
    latency = summary["sleep_latency"]
    rem_sleep = summary["rem_sleep_duration"]
    deep_sleep = summary["deep_sleep_duration"]
    restorative_sleep = rem_sleep + deep_sleep

    summary.update(
        {
            "sleep_efficiency_percent": _percentage(total_sleep, in_bed),
            "wake_after_sleep_onset": max(awake - latency, 0),
            "awake_percent": _percentage(awake, in_bed),
            "light_sleep_percent": _percentage(
                summary["light_sleep_duration"], total_sleep
            ),
            "rem_sleep_percent": _percentage(rem_sleep, total_sleep),
            "deep_sleep_percent": _percentage(deep_sleep, total_sleep),
            "restorative_sleep_duration": restorative_sleep,
            "restorative_sleep_percent": _percentage(restorative_sleep, total_sleep),
            "sleep_debt": max(sleep_target_seconds - total_sleep, 0),
            "sleep_goal_percent": _percentage(total_sleep, sleep_target_seconds),
        }
    )

    awakening_count, longest_sleep = _hypnogram_metrics(sessions)
    summary["awakening_count"] = awakening_count
    summary["longest_uninterrupted_sleep_duration"] = longest_sleep

    main_session = _main_session(sessions)
    if main_session is None:
        summary.update(
            {
                "main_enter_bed_time": None,
                "main_exit_bed_time": None,
                "sleep_midpoint": None,
                "nap_count": 0,
                "nap_sleep_duration": 0,
            }
        )
        return summary

    main_enter = _parse_datetime(main_session.get("enter_bed_time"))
    main_exit = _parse_datetime(main_session.get("exit_bed_time"))
    supplemental_sessions = [
        session for session in sessions if session is not main_session
    ]
    summary.update(
        {
            "main_enter_bed_time": main_enter,
            "main_exit_bed_time": main_exit,
            "sleep_midpoint": _midpoint(main_enter, main_exit),
            # The API does not label naps. The longest sleep session is treated as
            # the main sleep; all additional sessions are exposed as nap metrics.
            "nap_count": len(supplemental_sessions),
            "nap_sleep_duration": sum(
                _minutes_to_seconds(session.get("total_sleep_duration"))
                for session in supplemental_sessions
            ),
        }
    )
    return summary


def summarize_sleep_history(
    reports: list[dict[str, Any]],
    *,
    sleep_target_seconds: float = DEFAULT_SLEEP_TARGET_HOURS * 3600,
) -> dict[str, Any]:
    """Return seven- and thirty-day trends ending at the newest report date."""
    dated_reports = _dated_completed_reports(reports)
    all_dates = [
        parsed
        for report in reports
        if (parsed := _parse_date(report.get("date"))) is not None
    ]
    if not all_dates:
        return {}

    end_date = max(all_dates)
    result: dict[str, Any] = {}
    for window_days in (7, 30):
        cutoff = end_date - timedelta(days=window_days - 1)
        summaries = [
            summarize_sleep_report(report, sleep_target_seconds=sleep_target_seconds)
            for report_date, report in dated_reports
            if cutoff <= report_date <= end_date
        ]
        suffix = f"_{window_days}d"
        result[f"tracked_nights{suffix}"] = len(summaries)
        result[f"average_sleep_score_percent{suffix}"] = _average(
            summary.get("sleep_score_percent") for summary in summaries
        )
        result[f"average_total_sleep_duration{suffix}"] = _average(
            summary.get("total_sleep_duration") for summary in summaries
        )
        result[f"average_sleep_efficiency_percent{suffix}"] = _average(
            summary.get("sleep_efficiency_percent") for summary in summaries
        )
        result[f"average_sleep_latency{suffix}"] = _average(
            summary.get("sleep_latency") for summary in summaries
        )
        result[f"average_deep_sleep_percent{suffix}"] = _average(
            summary.get("deep_sleep_percent") for summary in summaries
        )
        result[f"average_rem_sleep_percent{suffix}"] = _average(
            summary.get("rem_sleep_percent") for summary in summaries
        )
        result[f"average_awakening_count{suffix}"] = _average(
            summary.get("awakening_count") for summary in summaries
        )
        result[f"cumulative_sleep_debt{suffix}"] = sum(
            _number(summary.get("sleep_debt")) for summary in summaries
        )
        result[f"bedtime_consistency{suffix}"] = _clock_consistency_minutes(
            summary.get("main_enter_bed_time") for summary in summaries
        )
        result[f"wake_time_consistency{suffix}"] = _clock_consistency_minutes(
            summary.get("main_exit_bed_time") for summary in summaries
        )

    return result


def _dated_completed_reports(
    reports: list[dict[str, Any]],
) -> list[tuple[date, dict[str, Any]]]:
    """Return reports with a valid date and at least one dictionary session."""
    dated: list[tuple[date, dict[str, Any]]] = []
    for report in reports:
        report_date = _parse_date(report.get("date"))
        if report_date is not None and _sessions(report):
            dated.append((report_date, report))
    return dated


def _sessions(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only dictionary sessions from a report."""
    raw_sessions = report.get("sessions", [])
    if not isinstance(raw_sessions, list):
        return []
    return [session for session in raw_sessions if isinstance(session, dict)]


def _main_session(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Select the longest-sleep session as the main daily sleep."""
    return max(
        sessions,
        key=lambda session: (
            _number(session.get("total_sleep_duration")),
            _number(session.get("total_session_duration")),
        ),
        default=None,
    )


def _session_datetimes(sessions: list[dict[str, Any]], key: str) -> list[datetime]:
    """Parse one timestamp field from every valid session."""
    return [
        parsed
        for session in sessions
        if (parsed := _parse_datetime(session.get(key))) is not None
    ]


def _hypnogram_metrics(sessions: list[dict[str, Any]]) -> tuple[int, int | float]:
    """Count sleep-to-awake transitions and the longest continuous sleep run."""
    awakenings = 0
    longest_sleep: int | float = 0

    for session in sessions:
        hypnogram = session.get("hypnogram")
        if not isinstance(hypnogram, dict):
            continue
        raw_segments = hypnogram.get("segments")
        if not isinstance(raw_segments, list):
            continue

        segments = sorted(
            (
                segment
                for segment in raw_segments
                if isinstance(segment, dict)
                and _optional_number(segment.get("start")) is not None
                and _optional_number(segment.get("end")) is not None
                and isinstance(segment.get("stage"), str)
            ),
            key=lambda segment: _number(segment["start"]),
        )
        previous_stage: str | None = None
        run_start: int | float | None = None
        run_end: int | float | None = None

        for segment in segments:
            stage = segment["stage"]
            start = _minutes_to_seconds(segment["start"])
            end = _minutes_to_seconds(segment["end"])
            if end < start:
                previous_stage = stage
                run_start = run_end = None
                continue

            if stage == "AWAKE" and previous_stage in SLEEP_STAGES:
                awakenings += 1

            if stage in SLEEP_STAGES:
                if run_start is None or run_end is None or start != run_end:
                    run_start = start
                run_end = end
                longest_sleep = max(longest_sleep, run_end - run_start)
            else:
                run_start = run_end = None

            previous_stage = stage

    return awakenings, longest_sleep


def _percentage(numerator: int | float, denominator: int | float) -> float | None:
    """Return a one-decimal percentage, or None when undefined."""
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _average(values: Iterable[Any]) -> float | None:
    """Average valid numbers with one-decimal stability."""
    numbers = [
        number for value in values if (number := _optional_number(value)) is not None
    ]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 1)


def _clock_consistency_minutes(values: Iterable[Any]) -> float | None:
    """Return mean circular clock-time deviation in minutes."""
    clock_seconds = [
        value.hour * 3600 + value.minute * 60 + value.second
        for value in values
        if isinstance(value, datetime)
    ]
    if len(clock_seconds) < 2:
        return None

    angles = [seconds / SECONDS_PER_DAY * math.tau for seconds in clock_seconds]
    mean_angle = math.atan2(
        sum(math.sin(angle) for angle in angles),
        sum(math.cos(angle) for angle in angles),
    )
    if mean_angle < 0:
        mean_angle += math.tau
    mean_seconds = mean_angle / math.tau * SECONDS_PER_DAY
    deviations = [
        min(
            abs(seconds - mean_seconds),
            SECONDS_PER_DAY - abs(seconds - mean_seconds),
        )
        for seconds in clock_seconds
    ]
    return round(sum(deviations) / len(deviations) / 60, 1)


def _midpoint(start: datetime | None, end: datetime | None) -> datetime | None:
    """Return the midpoint of a valid session interval."""
    if start is None or end is None or end < start:
        return None
    return start + (end - start) / 2


def _optional_number(value: Any) -> int | float | None:
    """Return a numeric API value, rejecting booleans and other shapes."""
    return (
        value
        if isinstance(value, int | float) and not isinstance(value, bool)
        else None
    )


def _number(value: Any) -> int | float:
    """Return numeric API values while treating absent/invalid values as zero."""
    return _optional_number(value) or 0


def _minutes_to_seconds(value: Any) -> int | float:
    """Normalize a numeric public-API minute value to seconds."""
    return _number(value) * SECONDS_PER_MINUTE


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
