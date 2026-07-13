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
- Hypnogram segment count as a sensor.
- A response-only `sleepme_thermostat.get_sleep_reports` action returns the lossless raw reports, including session IDs and every hypnogram segment, without storing that large health payload in Home Assistant's recorder.
- Sleep reports use a separate 30-minute polling cadence to protect the API request budget.

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

To tune the polling cadence: *Settings → Devices & Services → SleepMe → Configure → Poll interval*.

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

The normal sensors intentionally keep hypnogram arrays out of state attributes so Home Assistant's recorder does not duplicate a large health-data payload every refresh. Sleepme's consumer app documents heart rate, HRV, and respiration, but the current public `/sleep-reports` response does not expose those fields; this integration cannot create values that the public API does not return.

## Example automation: cool the bed at bedtime

```yaml
automation:
  - alias: SleepMe — cool bed at bedtime
    trigger:
      - platform: time
        at: "22:30:00"
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.dock_pro_ramon
        data:
          hvac_mode: auto
      - service: climate.set_temperature
        target:
          entity_id: climate.dock_pro_ramon
        data:
          temperature: 18
```

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

When editing translations, edit `custom_components/sleepme_thermostat/strings.json` first (the source of truth), then copy verbatim to `custom_components/sleepme_thermostat/translations/en.json`. CI fails if the two files diverge. Other language files (e.g. `es.json`) are hand-maintained from `strings.json`.

## License

[MIT](LICENSE).
