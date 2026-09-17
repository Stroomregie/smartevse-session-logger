"""Shared base entity for SmartEVSE Session Logger entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import CONF_NAME, DOMAIN
from .session_manager import SIGNAL_UPDATE, SessionManager


class SmartEvseLoggerEntity(Entity):
    """Base entity that redraws itself whenever the session manager saves new data."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SessionManager, entry: ConfigEntry, key: str) -> None:
        self._manager = manager
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, "SmartEVSE"),
            manufacturer="SmartEVSE Session Logger",
            model="Session Logger",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )
