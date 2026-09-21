# Sleep Tracker data and Home Assistant features

The ST501NA exposes two useful data paths through Sleepme's public API:

1. Live device status: occupancy, connectivity, bed temperature, room temperature, and room humidity.
2. Finalized daily reports: score, sessions, timestamps, duration totals, stage totals, and hypnogram segments.

Home Assistant polls live status at the configured device interval. It refreshes the newest seven-day report window every 30 minutes, one request per refresh. The four older windows that complete 30 calendar days of history never change, so each is fetched once after startup, one every two minutes, and then cached. The report coordinator therefore never spends more than two requests of the shared per-account budget at a time. Reports generally appear only after Sleepme finalizes a session, so report sensors are not real-time sleep-stage sensors.

The public report payload uses minutes for durations and hypnogram offsets. The integration converts these values to seconds at the aggregation boundary, matching Home Assistant's duration entity convention. The lossless response action returns the raw API values unchanged.

## Direct and derived sensors

| Feature | Source or formula | Classification |
|---|---|---|
| Bed occupied, environment/bed temperature, humidity, connectivity | Live device status | Direct |
| Sleep score, session count, duration/stage totals, latency, entry/exit | Daily report fields, summed across sessions | Direct aggregation |
| Sleep efficiency | `total sleep / in-bed duration × 100` | HA-derived |
| Wake after sleep onset (WASO) | `max(awake duration - sleep latency, 0)` | HA-derived approximation |
| Awake percentage | `awake duration / in-bed duration × 100` | HA-derived |
| Light, REM, deep percentage | Stage duration / total sleep × 100 | HA-derived |
| Restorative sleep | REM + deep duration and percentage | HA-derived convention |
| Sleep goal percentage | Total sleep / configured HA target × 100 | HA-derived |
| Nightly sleep debt | `max(configured target - total sleep, 0)` | HA-derived |
| Awakenings | Number of hypnogram transitions from a sleep stage to awake | HA-derived; not a movement count |
| Longest uninterrupted sleep | Longest contiguous run of light/REM/deep hypnogram segments | HA-derived |
| Main sleep and midpoint | Longest session; midpoint between its entry and exit | HA-derived heuristic |
| Additional sessions | Every session other than the longest, with total sleep summed | HA-derived heuristic; the API does not label naps |
| 7/30-day averages | Mean across completed reports in each calendar window | HA-derived |
| Bedtime / wake time variation | Mean circular clock-time deviation, in minutes | HA-derived; lower is more consistent |
| 7/30-day sleep debt over tracked nights | Sum of nightly debt across tracked nights only; untracked nights add nothing | HA-derived |

The personal sleep target is configured under *Settings → Devices & Services → SleepMe → Configure*. It defaults to eight hours and affects only HA-derived goal/debt sensors; it is not presented as medical guidance or a Sleepme recommendation.

## What pure Home Assistant can reproduce

| Sleepme-style capability | Pure HA result |
|---|---|
| Bed presence routines | Fully reproducible from live occupancy with a standard occupancy-triggered automation |
| Early to bed | Reproducible: occupancy within a configurable pre-bedtime window starts the Dock |
| Late to bed | Reproducible: an empty bed stays off at bedtime and later occupancy starts the Dock inside the overnight window |
| Wake up early | Reproducible: confirmed empty-bed state stops the Dock before the scheduled end |
| Snooze | Reproducible: occupancy at wake time uses a configurable extension; a later empty event can stop it sooner |
| Warm Awake | Reproducible with a time-and-occupancy automation; lead time, temperature, and duration remain explicit HA inputs |
| Return-to-bed temperature assistance | Approximate, user-controlled rule via a temporary-adjustment automation |
| Sleep-quality summaries and threshold alerts | Reproducible from finalized report sensors |
| Trend dashboards and correlations with room climate | Reproducible using Recorder/history/statistics and HA dashboards |
| Hiber-AI automatic temperature optimization | Not reproducible exactly; its model/inputs are proprietary and the public API exposes no equivalent control signal |
| Smart alarm based on current sleep stage | Not reproducible because reports and stages are finalized, not live |
| Heart rate, HRV, respiration | Not available in the current public response |
| True movement/disturbance events | Not available as labeled public fields; awakenings are only stage transitions |

## Known limitations

- Sleep reports belong to the Sleepme account, not to a device. The API gives no way to tell which tracker recorded a session, so two trackers on one account would show the same reports.
- Report sensors describe finalized sessions. Sleepme finalizes a report about 15 minutes after the sleeper leaves the bed.
- While the tracker is offline, its live sensors and Bed Occupancy are unavailable. The API keeps returning the last known values, and those are not shown as current.

## Blueprints

Ready-made automation blueprints for the routines above are being prepared separately and are not part of this release. Home Assistant only loads blueprints from `<config>/blueprints/`, and HACS only installs `custom_components/`, so they will be offered as imports by URL.

## Privacy and Recorder behavior

Normal entities expose only scalar values. Raw hypnogram arrays and session IDs are never added as state attributes or diagnostics, preventing Recorder from copying the full health payload every refresh. Use the response-only `sleepme_thermostat.get_sleep_reports` action for an explicit lossless fetch when needed.

## Language behavior

HA currently advertises 65 frontend locales. Entity and options strings use HA translation keys. The project includes English source strings, Spanish translations, and complete native Hungarian translations; every remaining HA locale is tested to resolve the English fallback, so controls and names remain usable without pretending that unreviewed machine translations are native-quality localization.
