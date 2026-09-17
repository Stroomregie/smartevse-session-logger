"""Sensors for SmartEVSE Session Logger."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SESSION_ACTIVE, SESSION_CONNECTED_IDLE, SESSION_IDLE
from .entity import SmartEvseLoggerEntity
from .session_manager import SessionManager

SESSION_STATE_ICONS = {
    SESSION_IDLE: "mdi:ev-plug-type2",
    SESSION_CONNECTED_IDLE: "mdi:power-plug-outline",
    SESSION_ACTIVE: "mdi:battery-charging-100",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: SessionManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SessionStateSensor(manager, entry),
            LastSessionEnergySensor(manager, entry),
            ReconciliationSensor(manager, entry),
        ]
    )


class SessionStateSensor(SmartEvseLoggerEntity, SensorEntity):
    """Current session state: idle / connected_idle / active."""

    _attr_translation_key = "session_state"
    _attr_options = [SESSION_IDLE, SESSION_CONNECTED_IDLE, SESSION_ACTIVE]
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, manager: SessionManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "session_state")

    @property
    def native_value(self) -> str:
        return self._manager.session_state

    @property
    def icon(self) -> str:
        return SESSION_STATE_ICONS.get(self._manager.session_state, "mdi:ev-station")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._manager.current_session
        if not session:
            return {}
        return {
            "session_id": session.get("id"),
            "start": session.get("start"),
            "energy_start_kwh": session.get("energy_start_kwh"),
            "mode_at_start": session.get("mode_at_start"),
            "recovered": session.get("recovered", False),
        }


class LastSessionEnergySensor(SmartEvseLoggerEntity, SensorEntity):
    """Energy charged during the most recently completed session."""

    _attr_translation_key = "last_session_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, manager: SessionManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "last_session_energy")

    @property
    def native_value(self) -> float | None:
        session = self._manager.last_completed_session
        return session.get("energy_kwh") if session else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = self._manager.last_completed_session
        if not session:
            return {}
        return {
            "session_id": session.get("id"),
            "start": session.get("start"),
            "end": session.get("end"),
            "end_reason": session.get("end_reason"),
            "energy_start_kwh": session.get("energy_start_kwh"),
            "energy_end_kwh": session.get("energy_end_kwh"),
            "mode_at_start": session.get("mode_at_start"),
            "recovered": session.get("recovered", False),
            "reconciliation_corrected": session.get("reconciliation_corrected", False),
        }


class ReconciliationSensor(SmartEvseLoggerEntity, SensorEntity):
    """Result of the last nightly completeness check."""

    _attr_translation_key = "reconciliation"
    _attr_options = ["unknown", "ok", "corrected", "unresolved"]
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:file-check-outline"

    def __init__(self, manager: SessionManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "reconciliation")

    @property
    def native_value(self) -> str:
        recon = self._manager.reconciliation
        if not recon.get("last_run"):
            return "unknown"
        if recon.get("unresolved_count"):
            return "unresolved"
        if recon.get("corrected_count"):
            return "corrected"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        recon = self._manager.reconciliation
        return {
            "last_run": recon.get("last_run"),
            "corrected_count": recon.get("corrected_count", 0),
            "unresolved_count": recon.get("unresolved_count", 0),
            "report_text": recon.get("report_text", ""),
        }
