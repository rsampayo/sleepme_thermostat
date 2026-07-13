API_URL = "https://api.developer.sleep.me/v1"

DOMAIN = "sleepme_thermostat"

MODEL_SLEEP_TRACKER = "ST501NA"

SERVICE_GET_SLEEP_REPORTS = "get_sleep_reports"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_START_DATE = "start_date"
ATTR_DAYS_BACK = "days_back"
ATTR_TIME_ZONE = "time_zone"

# The public API accepts the requested date plus at most six preceding days.
# Sleep reports are finalized after the sleeper has been out of bed for roughly
# 15 minutes, so a separate 30-minute coordinator is responsive without spending
# the scarce per-account request budget on every live-device poll.
MAX_SLEEP_REPORT_DAYS_BACK = 6
DEFAULT_SLEEP_REPORT_DAYS_BACK = 6
DEFAULT_SLEEP_REPORT_SCAN_INTERVAL = 30 * 60

PRESET_MAX_COOL = "Max Cool"
PRESET_MAX_HEAT = "Max Heat"

# Sentinel values documented by the SleepMe API:
#   set_temperature_c == -1.0  -> MAX COLD
#   set_temperature_c == 999.0 -> MAX HEAT
PRESET_TEMPERATURES = {PRESET_MAX_COOL: -1, PRESET_MAX_HEAT: 999}

# Documented temperature range for set_temperature_c (half-degree increments).
MIN_TEMP_C = 13.0
MAX_TEMP_C = 48.0

# Options flow
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SLEEP_TARGET_HOURS = "sleep_target_hours"
# 30s default keeps 3-device installs comfortably under the 9 req/min
# per-account ceiling (3 * 60/30 = 6 req/min). v4.1.0 release notes asked
# multi-device users to bump this manually; v4.1.1 makes it the default.
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

# Used only for HA-derived goal/debt sensors. Sleepme does not prescribe this
# value and users can change it in the integration options.
DEFAULT_SLEEP_TARGET_HOURS = 8.0
MIN_SLEEP_TARGET_HOURS = 4.0
MAX_SLEEP_TARGET_HOURS = 12.0

# The endpoint returns at most seven dates per call. The report coordinator
# pages across five non-overlapping windows every 30 minutes so rolling metrics
# can cover a full month without increasing the live-device polling cadence.
SLEEP_REPORT_HISTORY_DAYS = 30
