"""Constants for the SmartEVSE Session Logger integration."""
from __future__ import annotations

DOMAIN = "smartevse_session_logger"
STORAGE_VERSION = 1
PLATFORMS = ["sensor", "binary_sensor"]

# --- Config entry (set once, at setup) ---
CONF_NAME = "name"
CONF_STATE_SENSOR = "state_sensor"
CONF_PLUG_SENSOR = "plug_sensor"
CONF_ENERGY_SENSOR = "energy_sensor"

# --- Options (changeable via the gear icon) ---
CONF_TOTAL_ENERGY_SENSOR = "total_energy_sensor"
CONF_CURRENT_SENSOR = "current_sensor"
CONF_MODE_ENTITY = "mode_entity"

CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_SERVICE = "notify_service"

CONF_WATCHDOG_ENABLED = "watchdog_enabled"

CONF_RECONCILE_ENABLED = "reconcile_enabled"
CONF_RECONCILE_TIME = "reconcile_time"
CONF_RECONCILE_TOLERANCE = "reconcile_tolerance_kwh"

CONF_EXPORT_ENABLED = "export_enabled"
CONF_EXPORT_FREQUENCY = "export_frequency"
CONF_EXPORT_WEEKDAY = "export_weekday"
CONF_EXPORT_DAY_OF_MONTH = "export_day_of_month"
CONF_EXPORT_TIME = "export_time"

DEFAULT_NAME = "SmartEVSE"
DEFAULT_NOTIFY_ENABLED = False
DEFAULT_WATCHDOG_ENABLED = True
DEFAULT_RECONCILE_ENABLED = True
DEFAULT_RECONCILE_TIME = "04:30:00"
DEFAULT_RECONCILE_TOLERANCE = 0.02
DEFAULT_EXPORT_ENABLED = False
DEFAULT_EXPORT_FREQUENCY = "weekly"
DEFAULT_EXPORT_WEEKDAY = "0"  # Monday — kept as a string, matching SelectSelector option values
DEFAULT_EXPORT_DAY_OF_MONTH = 1
DEFAULT_EXPORT_TIME = "06:00:00"

EXPORT_FREQUENCIES = ["weekly", "monthly"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# --- SmartEVSE MQTT values (as published by the stock SmartEVSE-3 firmware) ---
EVSE_STATE_CHARGING = "Charging"
PLUG_STATE_CONNECTED = "Connected"
PLUG_STATE_DISCONNECTED = "Disconnected"
UNAVAILABLE_STATES = ("unknown", "unavailable", "", None)

# --- Session state machine ---
SESSION_IDLE = "idle"
SESSION_CONNECTED_IDLE = "connected_idle"
SESSION_ACTIVE = "active"

END_REASON_DISCONNECTED = "disconnected"
END_REASON_CHARGING_STOPPED = "charging_stopped"
END_REASON_WATCHDOG_RECOVERY = "watchdog_recovered"

WATCHDOG_INTERVAL_MINUTES = 60

EXPORT_DIR = "smartevse_session_logger"

# --- Events fired on the HA bus, for your own automations to hook into ---
# (e.g. to attach car-specific data such as a Tesla BLE state-of-charge
# reading, without this integration needing to know about any car brand)
EVENT_SESSION_STARTED = f"{DOMAIN}_session_started"
EVENT_SESSION_ENDED = f"{DOMAIN}_session_ended"
