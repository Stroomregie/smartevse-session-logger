"""Binary sensor for SmartEVSE Session Logger."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SESSION_ACTIVE
from .entity import SmartEvseLoggerEntity
from .session_manager import SessionManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: SessionManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargingBinarySensor(manager, entry)])


class ChargingBinarySensor(SmartEvseLoggerEntity, BinarySensorEntity):
    """On while a charge session is being actively logged."""

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, manager: SessionManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "charging")

    @property
    def is_on(self) -> bool:
        return self._manager.session_state == SESSION_ACTIVE
