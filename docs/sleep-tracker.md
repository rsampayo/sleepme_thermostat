# Sleep Tracker data and Home Assistant features

The ST501NA exposes two useful data paths through Sleepme's public API:

1. Live device status: occupancy, connectivity, bed temperature, room temperature, and room humidity.
2. Finalized daily reports: score, sessions, timestamps, duration totals, stage totals, and hypnogram segments.

Home Assistant polls live status at the configured device interval. It fetches reports every 30 minutes in five non-overlapping API-sized windows, yielding 30 calendar days of history. Reports generally appear only after Sleepme finalizes a session, so report sensors are not real-time sleep-stage sensors.

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
| Bed/wake consistency | Mean circular clock-time deviation, in minutes | HA-derived; lower is more consistent |
| 7/30-day cumulative debt | Sum of nightly debt across tracked nights | HA-derived |

The personal sleep target is configured under *Settings → Devices & Services → SleepMe → Configure*. It defaults to eight hours and affects only HA-derived goal/debt sensors; it is not presented as medical guidance or a Sleepme recommendation.

## What pure Home Assistant can reproduce

| Sleepme-style capability | Pure HA result |
|---|---|
| Bed presence routines | Fully reproducible from live occupancy using the included occupancy blueprint |
| Schedule plus early/late bedtime Dock response | Reproducible with occupancy, time triggers, and the presence-aware Dock blueprint |
| Wake-early and snooze behavior | Reproducible: delayed empty triggers cancel on a quick return; scheduled end remains deterministic |
| Return-to-bed temperature assistance | Approximate, user-controlled rule via the included temporary-adjustment blueprint |
| Sleep-quality summaries and threshold alerts | Reproducible from finalized report sensors |
| Trend dashboards and correlations with room climate | Reproducible using Recorder/history/statistics and HA dashboards |
| Hiber-AI automatic temperature optimization | Not reproducible exactly; its model/inputs are proprietary and the public API exposes no equivalent control signal |
| Smart alarm based on current sleep stage | Not reproducible because reports and stages are finalized, not live |
| Heart rate, HRV, respiration | Not available in the current public response |
| True movement/disturbance events | Not available as labeled public fields; awakenings are only stage transitions |

## Included blueprints

The repository ships four automation blueprints under `blueprints/automation/sleepme_thermostat/`. Import the desired raw GitHub URL in HA's Blueprint UI after this branch is merged.

- `tracker_occupancy_actions.yaml`: independent occupied/empty delays and arbitrary action selectors.
- `dock_presence_control.yaml`: an overnight window, early-start allowance, scheduled start/end, occupancy gating, and delayed shutdown.
- `dock_back_to_sleep.yaml`: waits for a return after an overnight absence, applies a signed target-temperature adjustment, and restores the original setpoint.
- `sleep_report_alert.yaml`: evaluates a finalized report against visible thresholds and exposes `sleepme_alert_message` to notification actions.

The return-to-bed automation is intentionally described as a heuristic rather than Hiber-AI. Start with a small signed adjustment appropriate for your HA temperature unit, observe comfort, and disable it if it conflicts with another Dock schedule.

## Privacy and Recorder behavior

Normal entities expose only scalar values. Raw hypnogram arrays and session IDs are never added as state attributes or diagnostics, preventing Recorder from copying the full health payload every refresh. Use the response-only `sleepme_thermostat.get_sleep_reports` action for an explicit lossless fetch when needed.

## Language behavior

HA currently advertises 65 frontend locales. Entity and options strings use HA translation keys. The project includes English source strings and Spanish translations; every remaining HA locale is tested to resolve the English fallback, so controls and names remain usable without pretending that unreviewed machine translations are native-quality localization.
