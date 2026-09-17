"""The SmartEVSE Session Logger integration.

Turns the entities your SmartEVSE already publishes over MQTT into a
persistent, exportable log of charge sessions — no OCPP backend required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PLATFORMS
from .session_manager import SessionManager

_LOGGER = logging.getLogger(__name__)

SERVICE_EXPORT_CSV = "export_csv"
SERVICE_FORCE_RECONCILIATION = "force_reconciliation"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERIOD = "period"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"

PERIOD_PRESETS = [
    "last_7_days",
    "last_30_days",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
]

EXPORT_CSV_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): str,
        vol.Optional(ATTR_PERIOD): vol.In(PERIOD_PRESETS),
        vol.Optional(ATTR_START_DATE): cv.date,
        vol.Optional(ATTR_END_DATE): cv.date,
    }
)

FORCE_RECONCILIATION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): str,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartEVSE Session Logger from a config entry."""
    manager = SessionManager(hass, entry)
    await manager.async_load()
    manager.async_setup_listeners()
    entry.async_on_unload(manager.async_unload_listeners)
    await manager.async_reconcile_on_startup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_setup_schedules(hass, entry, manager)
    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_setup_schedules(
    hass: HomeAssistant, entry: ConfigEntry, manager: SessionManager
) -> None:
    """Register the optional hourly watchdog, nightly reconciliation and periodic export."""
    if manager.watchdog_enabled:
        entry.async_on_unload(
            async_track_time_change(
                hass,
                lambda now: hass.async_create_task(manager.async_run_watchdog(now)),
                minute=0,
                second=0,
            )
        )

    if manager.reconcile_enabled:
        hour, minute, _ = _parse_hms(manager.reconcile_time)
        entry.async_on_unload(
            async_track_time_change(
                hass,
                lambda now: hass.async_create_task(manager.async_run_reconciliation(now)),
                hour=hour,
                minute=minute,
                second=0,
            )
        )

    if manager.export_enabled:
        hour, minute, _ = _parse_hms(manager.export_time)
        entry.async_on_unload(
            async_track_time_change(
                hass,
                lambda now: hass.async_create_task(_async_maybe_periodic_export(now, manager)),
                hour=hour,
                minute=minute,
                second=0,
            )
        )


def _parse_hms(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


async def _async_maybe_periodic_export(now: datetime, manager: SessionManager) -> None:
    """Called daily at the configured export time; only exports on the configured day."""
    today_start = dt_util.start_of_local_day(now)

    if manager.export_frequency == "weekly":
        if now.weekday() != manager.export_weekday:
            return
        start = today_start - timedelta(days=7)
        end = today_start
        label = f"week {start.date()} t/m {(end - timedelta(days=1)).date()}"
    else:  # monthly
        if now.day != manager.export_day_of_month:
            return
        end = today_start.replace(day=1)
        prev_month_last_day = end - timedelta(days=1)
        start = prev_month_last_day.replace(day=1)
        label = f"{start.strftime('%B %Y')}"

    await manager.async_run_periodic_export(start, end, label)


def _resolve_manager(hass: HomeAssistant, config_entry_id: str | None) -> SessionManager:
    managers: dict[str, SessionManager] = hass.data.get(DOMAIN, {})
    if not managers:
        raise ServiceValidationError("Geen SmartEVSE Session Logger is geconfigureerd")
    if config_entry_id:
        manager = managers.get(config_entry_id)
        if manager is None:
            raise ServiceValidationError(f"Onbekende config_entry_id: {config_entry_id}")
        return manager
    if len(managers) == 1:
        return next(iter(managers.values()))
    raise ServiceValidationError(
        "Er zijn meerdere SmartEVSE Session Logger-instanties geconfigureerd; "
        "geef config_entry_id mee om aan te geven welke je bedoelt."
    )


def _resolve_period(data: dict) -> tuple[datetime, datetime]:
    now = dt_util.now()
    today_start = dt_util.start_of_local_day(now)

    if data.get(ATTR_START_DATE) and data.get(ATTR_END_DATE):
        start = dt_util.start_of_local_day(
            datetime.combine(data[ATTR_START_DATE], datetime.min.time())
        )
        end = dt_util.start_of_local_day(
            datetime.combine(data[ATTR_END_DATE], datetime.min.time())
        ) + timedelta(days=1)
        return start, end

    period = data.get(ATTR_PERIOD, "last_30_days")
    if period == "last_7_days":
        return today_start - timedelta(days=7), today_start + timedelta(days=1)
    if period == "this_month":
        return today_start.replace(day=1), today_start + timedelta(days=1)
    if period == "last_month":
        this_month_start = today_start.replace(day=1)
        last_month_end = this_month_start
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
        return last_month_start, last_month_end
    if period == "this_year":
        return today_start.replace(month=1, day=1), today_start + timedelta(days=1)
    if period == "last_year":
        this_year_start = today_start.replace(month=1, day=1)
        return this_year_start.replace(year=this_year_start.year - 1), this_year_start
    # last_30_days (default)
    return today_start - timedelta(days=30), today_start + timedelta(days=1)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_EXPORT_CSV):
        return

    async def _handle_export_csv(call: ServiceCall) -> ServiceResponse:
        manager = _resolve_manager(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        start, end = _resolve_period(call.data)
        result = await manager.async_export_csv(start, end)
        result.pop("csv", None)
        return result

    async def _handle_force_reconciliation(call: ServiceCall) -> ServiceResponse:
        manager = _resolve_manager(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await manager.async_run_reconciliation(dt_util.now())
        recon = manager.reconciliation
        return {
            "report": recon.get("report_text"),
            "corrected": recon.get("corrected_count"),
            "unresolved": recon.get("unresolved_count"),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_CSV,
        _handle_export_csv,
        schema=EXPORT_CSV_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_RECONCILIATION,
        _handle_force_reconciliation,
        schema=FORCE_RECONCILIATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
