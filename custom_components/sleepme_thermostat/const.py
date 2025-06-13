from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
)

# Configuration Constants
DOMAIN = "sleepme_thermostat"
MANUFACTURER = "Sleepme Inc."
DEFAULT_API_URL = "https://api.developer.sleep.me/v1"

# Polling and Timeout Constants
DEFAULT_POLLING_INTERVAL_S = 60
DEFAULT_TIMEOUT_S = 30
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_BACKOFF_FACTOR = 30

# HVAC Action/Mode Constants
HVAC_ACTION_COOLING = "cooling"
HVAC_ACTION_HEATING = "heating"
HVAC_ACTION_IDLE = "idle"
HVAC_ACTION_OFF = "off"
HVAC_MODES = [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]

# Preset Mode Constants
PRESET_PRECONDITIONING = "Preconditioning"


# Supported Features
SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
)

# Entity Naming Constants
SCHEDULE_SWITCH_NAME = "Device Schedule"