#!/usr/bin/env python3
"""Read-only probe of the SleepMe developer API for the Sleep Tracker work (PR #49).

Answers the questions the public docs leave open, using one real account:

  1. Window direction: is `start_date` the END of the window (PR assumption) or the START?
  2. Session shape: which keys exist, which durations are null, is `NO_DATA` used,
     any undocumented fields (device_id especially)?
  3. Empty-day response: 404, `{"reports": []}`, or a report with empty sessions?
  4. `days_back=7`: clamped, rejected with 400, or accepted?
  5. Tracker identity: id prefix, `attachments`, `about.model`, `connectivity`, `control`.
  6. Trailing slash: `/sleep-reports` vs `/sleep-reports/`.
  7. (opt-in) 429 shape: does the API send `Retry-After`?

Every call is a GET. Nothing is written to the account. Calls are spaced out so
they fit inside the per-account budget alongside a running Home Assistant.

Usage:
    SLEEPME_TOKEN=... python3 scripts/probe_sleep_reports.py [--tz America/Mexico_City]
    python3 scripts/probe_sleep_reports.py            # prompts for the token, hidden
    python3 scripts/probe_sleep_reports.py --probe-429  # also exhausts the budget once

The token is never printed. The raw responses are saved locally with
serial numbers, MAC and IP addresses redacted; share the SUMMARY block.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_URL = "https://api.developer.sleep.me/v1"
SPACING_SECONDS = 65  # one call per discrete minute window, HA keeps polling meanwhile
TRACKER_MODEL = "ST501NA"

DOCUMENTED_REPORT_KEYS = {"date", "sessions", "sleep_score_percent"}
DOCUMENTED_SESSION_KEYS = {
    "id",
    "enter_bed_time",
    "exit_bed_time",
    "awake_duration",
    "rem_sleep_duration",
    "light_sleep_duration",
    "deep_sleep_duration",
    "total_sleep_duration",
    "in_bed_duration",
    "total_session_duration",
    "sleep_latency",
    "hypnogram",
}
DURATION_KEYS = {
    "awake_duration",
    "rem_sleep_duration",
    "light_sleep_duration",
    "deep_sleep_duration",
    "total_sleep_duration",
    "in_bed_duration",
    "total_session_duration",
    "sleep_latency",
}
DOCUMENTED_STAGES = {"AWAKE", "LIGHT_SLEEP", "REM_SLEEP", "DEEP_SLEEP", "NO_DATA"}

REDACT_KEYS = {"serial_number", "mac_address", "ip_address", "lan_address"}


class Call:
    """One HTTP exchange, kept for the summary and the raw dump."""

    def __init__(self, label: str, path: str, params: dict[str, Any] | None) -> None:
        self.label = label
        self.path = path
        self.params = params or {}
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.body: Any = None
        self.text: str = ""
        self.error: str | None = None
        self.elapsed_ms: int = 0

    @property
    def url(self) -> str:
        query = f"?{urllib.parse.urlencode(self.params)}" if self.params else ""
        return f"{API_URL}{self.path}{query}"


def request(token: str, call: Call) -> Call:
    req = urllib.request.Request(call.url, headers={"Authorization": f"Bearer {token}"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            call.status = resp.status
            call.headers = {k: v for k, v in resp.headers.items()}
            call.text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        call.status = err.code
        call.headers = {k: v for k, v in err.headers.items()}
        call.text = err.read().decode("utf-8", errors="replace")
    except Exception as err:
        call.error = f"{type(err).__name__}: {err}"
    call.elapsed_ms = int((time.monotonic() - started) * 1000)
    if call.text:
        try:
            call.body = json.loads(call.text)
        except ValueError:
            call.body = None
    return call


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if k in REDACT_KEYS else redact(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def short_id(device_id: str) -> str:
    """Keep the prefix (the thing we are probing) and mask the rest."""
    match = re.match(r"^([a-z0-9]{1,3}-)", device_id)
    prefix = match.group(1) if match else ""
    return f"{prefix}{'*' * max(0, len(device_id) - len(prefix) - 3)}{device_id[-3:]}"


def pause(seconds: int, why: str) -> None:
    print(f"    ... waiting {seconds}s ({why})", flush=True)
    time.sleep(seconds)


def analyse_reports(call: Call, start_date: dt.date) -> dict[str, Any]:
    out: dict[str, Any] = {"status": call.status}
    body = call.body
    if not isinstance(body, dict) or not isinstance(body.get("reports"), list):
        out["envelope"] = f"UNEXPECTED: {type(body).__name__}"
        out["raw_head"] = call.text[:200]
        return out
    reports = body["reports"]
    out["envelope"] = "reports list"
    out["top_level_keys"] = sorted(body.keys())
    dates: list[dt.date] = []
    report_extra_keys: set[str] = set()
    session_keys: set[str] = set()
    session_extra_keys: set[str] = set()
    null_durations: set[str] = set()
    stages: set[str] = set()
    sessions_per_report: list[int] = []
    hypnogram_missing = 0
    total_sessions = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        report_extra_keys |= set(report.keys()) - DOCUMENTED_REPORT_KEYS
        try:
            dates.append(dt.date.fromisoformat(str(report.get("date"))))
        except ValueError:
            pass
        sessions = report.get("sessions") or []
        sessions_per_report.append(len(sessions))
        for session in sessions:
            if not isinstance(session, dict):
                continue
            total_sessions += 1
            session_keys |= set(session.keys())
            session_extra_keys |= set(session.keys()) - DOCUMENTED_SESSION_KEYS
            for key in DURATION_KEYS:
                if key in session and session[key] is None:
                    null_durations.add(key)
            hypnogram = session.get("hypnogram")
            if not isinstance(hypnogram, dict) or not isinstance(
                hypnogram.get("segments"), list
            ):
                hypnogram_missing += 1
                continue
            for segment in hypnogram["segments"]:
                if isinstance(segment, dict):
                    stages.add(str(segment.get("stage")))
    out["report_count"] = len(reports)
    out["dates"] = [d.isoformat() for d in sorted(dates)]
    out["sessions_per_report"] = sessions_per_report
    out["session_keys"] = sorted(session_keys)
    out["undocumented_report_keys"] = sorted(report_extra_keys)
    out["undocumented_session_keys"] = sorted(session_extra_keys)
    out["null_durations_seen"] = sorted(null_durations)
    out["stages_seen"] = sorted(stages)
    out["undocumented_stages"] = sorted(stages - DOCUMENTED_STAGES)
    out["sessions_without_hypnogram"] = hypnogram_missing
    out["total_sessions"] = total_sessions
    if dates:
        newest, oldest = max(dates), min(dates)
        if newest <= start_date:
            out["window_direction"] = (
                f"start_date is the END of the window (newest {newest} <= {start_date}). "
                "PR #49 assumption holds."
            )
        elif oldest >= start_date:
            out["window_direction"] = (
                f"start_date is the START of the window (oldest {oldest} >= {start_date}). "
                "PR #49 assumption is WRONG; window stepping must reverse."
            )
        else:
            out["window_direction"] = (
                f"AMBIGUOUS: dates span {oldest}..{newest} around {start_date}."
            )
    else:
        out["window_direction"] = "no dated reports returned; cannot infer"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--tz",
        default=None,
        help="IANA time zone to send (default: the Dock's time_zone if found, else UTC)",
    )
    parser.add_argument(
        "--probe-429",
        action="store_true",
        help="Also exhaust the per-minute budget once to capture the 429 shape "
        "(will make Home Assistant's polling fail for about a minute)",
    )
    parser.add_argument(
        "--out",
        default="probe_sleep_reports_output.json",
        help="Where to save the redacted raw responses",
    )
    args = parser.parse_args()

    token = os.environ.get("SLEEPME_TOKEN") or getpass.getpass("SleepMe API token: ")
    token = token.strip()
    if not token:
        print("No token given.", file=sys.stderr)
        return 2

    calls: list[Call] = []
    summary: dict[str, Any] = {}

    def run(label: str, path: str, params: dict[str, Any] | None = None) -> Call:
        call = request(token, Call(label, path, params))
        calls.append(call)
        state = call.error or f"HTTP {call.status}"
        print(f"[{len(calls)}] {label}: {state} in {call.elapsed_ms} ms", flush=True)
        return call

    # ---- 1. Device inventory -------------------------------------------------
    devices = run("GET /devices", "/devices")
    device_list = devices.body if isinstance(devices.body, list) else []
    summary["devices"] = [
        {
            "id": short_id(str(d.get("id", ""))),
            "id_prefix": (
                re.match(r"^([a-z0-9]{1,3}-)", str(d.get("id", ""))) or [None, None]
            )[1],
            "name": d.get("name"),
            "attachments": d.get("attachments"),
            "list_keys": sorted(d.keys()),
        }
        for d in device_list
        if isinstance(d, dict)
    ]

    tracker_id: str | None = None
    dock_tz: str | None = None
    for device in device_list:
        if not isinstance(device, dict) or "id" not in device:
            continue
        pause(SPACING_SECONDS, "budget spacing")
        detail = run(
            f"GET /devices/{short_id(device['id'])}", f"/devices/{device['id']}"
        )
        body = detail.body if isinstance(detail.body, dict) else {}
        about = body.get("about") or {}
        model = about.get("model")
        entry = {
            "id": short_id(device["id"]),
            "model": model,
            "top_level_keys": sorted(body.keys()),
            "has_control": "control" in body,
            "control_value": body.get("control") if "control" in body else "<absent>",
            "has_connectivity": "connectivity" in body,
            "connectivity_keys": sorted((body.get("connectivity") or {}).keys())
            if isinstance(body.get("connectivity"), dict)
            else None,
            "status_keys": sorted((body.get("status") or {}).keys())
            if isinstance(body.get("status"), dict)
            else None,
        }
        summary.setdefault("device_details", []).append(entry)
        if str(model).upper() == TRACKER_MODEL and tracker_id is None:
            tracker_id = device["id"]
        if isinstance(body.get("control"), dict) and body["control"].get("time_zone"):
            dock_tz = dock_tz or body["control"]["time_zone"]

    summary["tracker_found"] = tracker_id is not None
    if tracker_id:
        summary["tracker_id_prefix"] = (
            re.match(r"^([a-z0-9]{1,3}-)", tracker_id) or [None, None]
        )[1]

    tz = args.tz or dock_tz or "UTC"
    summary["time_zone_used"] = tz
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)

    # ---- 2. Window direction + session shape (one call) ----------------------
    pause(SPACING_SECONDS, "budget spacing")
    main_call = run(
        "GET /sleep-reports start_date=yesterday days_back=6",
        "/sleep-reports",
        {"start_date": yesterday.isoformat(), "days_back": 6, "time_zone": tz},
    )
    summary["window_and_shape"] = analyse_reports(main_call, yesterday)

    # ---- 3. Empty day (two years back, before any tracker existed) -----------
    pause(SPACING_SECONDS, "budget spacing")
    empty_day = today - dt.timedelta(days=730)
    empty_call = run(
        "GET /sleep-reports on a day with no data",
        "/sleep-reports",
        {"start_date": empty_day.isoformat(), "days_back": 0, "time_zone": tz},
    )
    summary["empty_day"] = {
        "status": empty_call.status,
        "body": redact(empty_call.body)
        if empty_call.body is not None
        else empty_call.text[:300],
    }

    # ---- 4. days_back above the documented max -------------------------------
    pause(SPACING_SECONDS, "budget spacing")
    over_call = run(
        "GET /sleep-reports days_back=7",
        "/sleep-reports",
        {"start_date": yesterday.isoformat(), "days_back": 7, "time_zone": tz},
    )
    over = analyse_reports(over_call, yesterday)
    summary["days_back_7"] = {
        "status": over_call.status,
        "report_count": over.get("report_count"),
        "dates": over.get("dates"),
        "body_head_if_error": over_call.text[:300]
        if (over_call.status or 0) >= 400
        else None,
    }

    # ---- 5. Trailing slash ---------------------------------------------------
    pause(SPACING_SECONDS, "budget spacing")
    slash_call = run(
        "GET /sleep-reports/ (trailing slash)",
        "/sleep-reports/",
        {"start_date": yesterday.isoformat(), "days_back": 0, "time_zone": tz},
    )
    summary["trailing_slash"] = {"status": slash_call.status, "error": slash_call.error}

    # ---- 6. UTC default shift ------------------------------------------------
    pause(SPACING_SECONDS, "budget spacing")
    no_tz_call = run(
        "GET /sleep-reports without time_zone",
        "/sleep-reports",
        {"start_date": yesterday.isoformat(), "days_back": 0},
    )
    summary["without_time_zone"] = {
        "status": no_tz_call.status,
        "dates": analyse_reports(no_tz_call, yesterday).get("dates"),
        "dates_with_tz_days_back_0": [
            d
            for d in summary["window_and_shape"].get("dates", [])
            if d == yesterday.isoformat()
        ],
    }

    # ---- 7. Optional: 429 shape ----------------------------------------------
    if args.probe_429:
        print("\nExhausting the per-minute budget to capture a 429 (opt-in) ...")
        got_429: Call | None = None
        for i in range(14):
            burst = run(f"burst {i + 1}", "/devices")
            if burst.status == 429:
                got_429 = burst
                break
            time.sleep(1)
        summary["rate_limit_429"] = (
            {
                "status": got_429.status,
                "retry_after_header": got_429.headers.get("Retry-After"),
                "all_headers": {
                    k: v
                    for k, v in got_429.headers.items()
                    if k.lower() != "set-cookie"
                },
                "body": got_429.text[:500],
            }
            if got_429
            else "no 429 after 14 rapid calls"
        )

    # ---- Save + print -------------------------------------------------------
    dump = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "summary": summary,
        "calls": [
            {
                "label": c.label,
                "path": c.path,
                "params": c.params,
                "status": c.status,
                "error": c.error,
                "elapsed_ms": c.elapsed_ms,
                "headers": {
                    k: v for k, v in c.headers.items() if k.lower() != "set-cookie"
                },
                "body": redact(c.body) if c.body is not None else c.text[:1000],
            }
            for c in calls
        ],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, indent=2)

    print("\n================ SUMMARY (safe to share) ================")
    print(json.dumps(summary, indent=2))
    print(f"\nRaw responses (redacted) saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
