API_URL = "https://api.developer.sleep.me/v1"

DOMAIN = "sleepme_thermostat"

PRESET_MAX_COOL = "Max Cool"
PRESET_MAX_HEAT = "Max Heat"

# Sentinel values documented by the SleepMe API:
#   set_temperature_c == -1.0  -> MAX COLD
#   set_temperature_c == 999.0 -> MAX HEAT
PRESET_TEMPERATURES = {PRESET_MAX_COOL: -1, PRESET_MAX_HEAT: 999}

# Documented temperature range for set_temperature_c (half-degree increments).
MIN_TEMP_C = 13.0
MAX_TEMP_C = 48.0

# Device-ID prefixes the v1 API cannot serve. Gen-2 / Chilipad 2.0 units use
# "x2-" IDs that v1 GET/PATCH /devices/{id} rejects with HTTP 400
# "invalid device ID", while the v2 device surface returns 403 for developer
# tokens. The integration can enumerate these devices via GET /devices but can
# neither read their status nor control them, so the config flow blocks them
# with a clear message. See https://github.com/rsampayo/sleepme_thermostat/issues/46.
UNSUPPORTED_DEVICE_ID_PREFIXES = ("x2-",)

# Options flow
CONF_SCAN_INTERVAL = "scan_interval"
# 30s default keeps 3-device installs comfortably under the 9 req/min
# per-account ceiling (3 * 60/30 = 6 req/min). v4.1.0 release notes asked
# multi-device users to bump this manually; v4.1.1 makes it the default.
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300
