# SleepMe Integration

[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom_Repository-41BDF5.svg)](https://github.com/hacs/default)
[![Quality Scale](https://img.shields.io/badge/Quality_Scale-silver-c0c0c0.svg)](https://www.home-assistant.io/docs/quality_scale/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/test.yml/badge.svg)](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/test.yml)
[![Validate HACS](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/validate.yml/badge.svg)](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/validate.yml)
[![CodeQL](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/codeql.yml/badge.svg)](https://github.com/rsampayo/sleepme_thermostat/actions/workflows/codeql.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

> A Home Assistant custom integration for **SleepMe Chilipad climate systems and the ST501NA Sleep Tracker**, backed by the [sleep.me developer API](https://docs.developer.sleep.me/api/).

## Supported devices

| Model | Product | Support |
|---|---|---|
| DP999NA | Chilipad Dock Pro | Climate control and complete live device status |
| DP723NA / `x2-…` devices | Chilipad 2.0 | Climate control and complete live device status |
| ST501NA | Sleepme Sleep Tracker | Live occupancy/environment data and complete public-API sleep reports |

## Features

### Chilipad climate systems

- Set bed temperature (13–48°C, half-degree steps, plus `Max Cool` / `Max Heat` presets per API contract).
- Turn the device on/off via HVAC mode.
- Water-level-low binary sensor for proactive alerts.
- Connectivity binary sensor.
- Five diagnostic sensors: IP, LAN, brightness, display unit, time zone.
- Configurable polling interval (10–300 s).
- Reauth flow when the API token rotates — no integration removal needed.
- Multi-device support: configure multiple Dock Pros under one HA install.
- Long-term statistics for brightness.

### ST501NA Sleep Tracker

- Real-time bed occupancy, connectivity, bed temperature, room temperature, and humidity.
- Latest completed daily sleep report with score, session count, bed-entry/exit times, sleep latency, and total/in-bed/asleep/awake/light/REM/deep durations.
- Multiple sessions (for example, naps plus overnight sleep) are aggregated into daily sensors.
- Derived sleep efficiency, wake after sleep onset, stage percentages, restorative sleep, awakenings, longest uninterrupted sleep, main-session timing, sleep midpoint, and additional-session metrics.
- Configurable sleep goal with nightly goal percentage, sleep debt, and cumulative 7/30-day debt.
- Seven- and thirty-day averages plus bedtime/wake-time consistency.
- Five ready-to-import automation blueprints for occupancy actions, presence-aware Dock control with an occupied wake-time extension, return-to-bed temperature adjustment, Warm Awake, and sleep-report alerts.
- A response-only `sleepme_thermostat.get_sleep_reports` action returns the lossless raw reports, including session IDs and every hypnogram segment, without storing that large health payload in Home Assistant's recorder.
- Sleep reports page over 30 days at a separate 30-minute polling cadence to protect the API request budget.

See [Sleep Tracker features, formulas, and limitations](docs/sleep-tracker.md) for the exact direct-versus-derived boundary. In particular, the public API does not currently expose biometrics or live sleep stages, so HA cannot reproduce those consumer-app features honestly.

## Requirements

- Home Assistant Core **2026.1** or newer (tested on 2026.1, 2026.3, 2026.5).
- A sleep.me account with at least one supported Chilipad or Sleep Tracker device.
- A developer API token (generated in the sleep.me account portal, free).

## Installation

### HACS (recommended)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/rsampayo/sleepme_thermostat`, category *Integration*.
2. Install **SleepMe**.
3. Restart Home Assistant.
4. *Settings → Devices & Services → Add Integration → SleepMe*.

### Manual

1. Download the repository.
2. Copy `custom_components/sleepme_thermostat/` into `<config>/custom_components/`.
3. Restart Home Assistant.
4. Add the integration via the UI.

## Configuration

1. Generate an API token: sleep.me website → account → *Developer API* → *Create new token*.
2. *Settings → Devices & Services → Add Integration → SleepMe*.
3. Paste the token; pick the Chilipad or Sleep Tracker from the discovered list.

To tune the polling cadence: *Settings → Devices & Services → SleepMe → Configure → Poll interval*. Sleep Tracker entries also expose a 4–12 hour personal sleep target used only by HA's goal/debt calculations.

## Entities created

### Chilipad climate systems

| Platform       | Entity                       | Notes                              |
|----------------|------------------------------|------------------------------------|
| climate        | Dock Pro *{name}*            | Target temp, on/off, Max Cool/Heat |
| binary_sensor  | Water Level                  | Device class: PROBLEM              |
| binary_sensor  | Connected                    | Device class: CONNECTIVITY         |
| sensor         | IP Address                   | Diagnostic                         |
| sensor         | LAN Address                  | Diagnostic                         |
| sensor         | Brightness Level (%)         | Diagnostic, in long-term statistics |
| sensor         | Display Temperature Unit     | Diagnostic                         |
| sensor         | Time Zone                    | Diagnostic                         |

### ST501NA Sleep Tracker

| Platform | Entity | Notes |
|---|---|---|
| binary_sensor | Bed Occupancy | Live `user_detected`; device class: OCCUPANCY |
| binary_sensor | Connected | Device class: CONNECTIVITY |
| sensor | Environment Humidity | Live percentage |
| sensor | Environment Temperature | Live room temperature |
| sensor | Bed Temperature | Live in-bed temperature |
| sensor | Last Sleep Report | Date of the latest completed report |
| sensor | Sleep Score | Percentage |
| sensor | Sleep Sessions | Sessions aggregated into the report |
| sensor | Entered Bed / Exited Bed | Earliest entry and latest exit timestamps |
| sensor | Total Session / In-bed / Total Sleep Duration | Daily totals in seconds |
| sensor | Awake / Light / REM / Deep Sleep Duration | Daily stage totals in seconds |
| sensor | Sleep Latency | Sum across the day's sessions, in seconds |
| sensor | Hypnogram Segments | Total raw segment count |
| sensor | Sleep Efficiency / Wake After Sleep Onset | Derived from public duration fields |
| sensor | Awake / Light / REM / Deep / Restorative Percentage | Derived daily composition |
| sensor | Restorative Sleep / Longest Uninterrupted Sleep | Derived durations |
| sensor | Sleep Goal / Sleep Debt | Based on the configurable HA target |
| sensor | Awakenings | Sleep-to-awake hypnogram transitions |
| sensor | Main Sleep Entered/Exited Bed / Sleep Midpoint | Longest session is treated as main sleep |
| sensor | Additional Sleep Sessions / Duration | All sessions other than the longest |
| sensor | 7-day and 30-day averages | Score, duration, efficiency, latency, stages, awakenings |
| sensor | 7-day and 30-day consistency | Mean clock-time deviation for bedtime and wake time |
| sensor | 7-day and 30-day cumulative debt | Sum of per-night debt in the window |
| sensor | IP / LAN / Firmware | Diagnostic |

## Fetch complete raw sleep reports

The public API returns up to seven days per request. Use the response-only action when an automation needs the complete session and hypnogram payload:

```yaml
action: sleepme_thermostat.get_sleep_reports
data:
  config_entry_id: 01JEXAMPLECONFIGENTRY
  start_date: "2026-07-13"
  days_back: 6
  time_zone: Europe/Budapest
response_variable: sleepme_data
```

The raw API expresses report durations and hypnogram offsets in minutes. Sensor entities normalize them to seconds for Home Assistant's duration device class; the response-only action deliberately preserves the raw minute values. Normal sensors intentionally keep hypnogram arrays out of state attributes so Home Assistant's recorder does not duplicate a large health-data payload every refresh. Sleepme's consumer app documents heart rate, HRV, and respiration, but the current public `/sleep-reports` response does not expose those fields; this integration cannot create values that the public API does not return.

## Automation blueprints

Import any blueprint in *Settings → Automations & Scenes → Blueprints → Import Blueprint* using its raw URL:

| Blueprint | What it reproduces with HA data |
|---|---|
| [Occupancy actions](blueprints/automation/sleepme_thermostat/tracker_occupancy_actions.yaml) | Run lights, scenes, locks, or notifications when bed occupancy changes |
| [Presence-aware Dock control](blueprints/automation/sleepme_thermostat/dock_presence_control.yaml) | Early/late bedtime, scheduled start, early wake, and snooze-safe shutdown |
| [Return-to-bed adjustment](blueprints/automation/sleepme_thermostat/dock_back_to_sleep.yaml) | Temporary configurable Dock adjustment after an overnight absence and return |
| [Warm-awake routine](blueprints/automation/sleepme_thermostat/tracker_warm_awake.yaml) | Warm an occupied bed before wake time for a configurable duration, then stop |
| [Sleep report alert](blueprints/automation/sleepme_thermostat/sleep_report_alert.yaml) | Notify on transparent score, duration, efficiency, latency, and deep-sleep thresholds |

These are deterministic HA rules, not a clone of Sleepme's proprietary Hiber-AI model. A stock-card dashboard example is available at [docs/examples/sleep_tracker_dashboard.yaml](docs/examples/sleep_tracker_dashboard.yaml).

All HA-supported frontend languages can load and use the integration. Entity and option text uses HA's translation system; Spanish and complete native Hungarian translations are included, while every remaining locale receives HA's built-in English fallback instead of broken or missing labels.

## Troubleshooting

**"API token rejected" / reauth banner keeps appearing.**
Tokens can be rotated or revoked in the sleep.me developer portal. When that happens, the integration triggers a reauth prompt on *Settings → Devices & Services*. Click *Reauthenticate*, paste a fresh token, done. No HA restart needed.

**"Cannot connect to SleepMe API."**
The sleep.me API is aggressively rate-limited. Transient failures are normal — the integration honors `Retry-After` and recovers on the next poll. If the entity stays unavailable for more than a few minutes, check the log under `custom_components.sleepme_thermostat`.

**Polling too aggressive / not aggressive enough.**
The default live-device poll interval is **30 seconds**. To change it: *Settings → Devices & Services → SleepMe → Configure*. Acceptable range 10–300 s. Lower values feel snappier but consume more of your per-minute API budget. Tracker sleep reports always use a separate 30-minute interval.

**Sharing a bug report.**
Open the device page in *Settings → Devices & Services*, click ⋮, choose *Download diagnostics*. The downloaded JSON has your API token (and MAC, IP, serial) redacted. Attach it to a GitHub issue.

**Adjusting log verbosity.**
The integration registers one logger: `custom_components.sleepme_thermostat`. Use *Settings → System → Logs* or the `logger.set_level` service to bump it to debug temporarily.

## Tested against

| HA Core   | Python | Status |
|-----------|--------|--------|
| 2026.1.x  | 3.13   | tested |
| 2026.3.x  | 3.14   | tested |
| 2026.5.x  | 3.14   | tested |

Older HA versions may work but are not in the CI matrix.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

When editing translations, edit `custom_components/sleepme_thermostat/strings.json` first (the source of truth), then copy verbatim to `custom_components/sleepme_thermostat/translations/en.json`. CI fails if the two files diverge. Other language files (such as `es.json` and `hu.json`) are hand-maintained from `strings.json`.

## License

[MIT](LICENSE).
