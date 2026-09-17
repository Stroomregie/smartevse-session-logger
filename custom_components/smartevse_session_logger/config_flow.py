"""Config flow for SmartEVSE Session Logger — fully UI-based, no YAML needed."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_CURRENT_SENSOR,
    CONF_ENERGY_SENSOR,
    CONF_EXPORT_DAY_OF_MONTH,
    CONF_EXPORT_ENABLED,
    CONF_EXPORT_FREQUENCY,
    CONF_EXPORT_TIME,
    CONF_EXPORT_WEEKDAY,
    CONF_MODE_ENTITY,
    CONF_NAME,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_PLUG_SENSOR,
    CONF_RECONCILE_ENABLED,
    CONF_RECONCILE_TIME,
    CONF_RECONCILE_TOLERANCE,
    CONF_STATE_SENSOR,
    CONF_TOTAL_ENERGY_SENSOR,
    CONF_WATCHDOG_ENABLED,
    DEFAULT_EXPORT_DAY_OF_MONTH,
    DEFAULT_EXPORT_FREQUENCY,
    DEFAULT_EXPORT_TIME,
    DEFAULT_EXPORT_WEEKDAY,
    DEFAULT_NAME,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_RECONCILE_ENABLED,
    DEFAULT_RECONCILE_TIME,
    DEFAULT_RECONCILE_TOLERANCE,
    DEFAULT_WATCHDOG_ENABLED,
    DOMAIN,
    EXPORT_FREQUENCIES,
    WEEKDAYS,
)


def _entity_selector(domain: str | None = "sensor") -> selector.Selector:
    if domain is None:
        return selector.EntitySelector(selector.EntitySelectorConfig())
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


class SmartEvseSessionLoggerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: which entities represent your SmartEVSE."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip() or DEFAULT_NAME
            await self.async_set_unique_id(slugify(name))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_STATE_SENSOR): _entity_selector("sensor"),
                vol.Required(CONF_PLUG_SENSOR): _entity_selector("sensor"),
                vol.Required(CONF_ENERGY_SENSOR): _entity_selector("sensor"),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "OptionsFlowHandler":
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Adjust optional entities, notifications and scheduled checks after setup.

    No __init__/config_entry assignment here on purpose: since HA 2024.12,
    self.config_entry is injected by the flow manager, and manually setting
    it raises (config_entry is a read-only property on the base class).
    """

    def _current(self, key: str, default: Any = None) -> Any:
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        return self.async_show_menu(
            step_id="init",
            menu_options=["entities", "notifications", "automation"],
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            cleaned = {k: v for k, v in user_input.items() if v not in (None, "")}
            new_options = {**self.config_entry.options}
            for key in (CONF_TOTAL_ENERGY_SENSOR, CONF_CURRENT_SENSOR, CONF_MODE_ENTITY):
                new_options.pop(key, None)
            new_options.update(cleaned)
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TOTAL_ENERGY_SENSOR,
                    description={"suggested_value": self._current(CONF_TOTAL_ENERGY_SENSOR)},
                ): _entity_selector("sensor"),
                vol.Optional(
                    CONF_CURRENT_SENSOR,
                    description={"suggested_value": self._current(CONF_CURRENT_SENSOR)},
                ): _entity_selector("sensor"),
                vol.Optional(
                    CONF_MODE_ENTITY,
                    description={"suggested_value": self._current(CONF_MODE_ENTITY)},
                ): _entity_selector(None),
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema)

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            new_options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFY_ENABLED,
                    default=self._current(CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    description={"suggested_value": self._current(CONF_NOTIFY_SERVICE)},
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="notifications",
            data_schema=schema,
            description_placeholders={"example": "notify.email_sander"},
        )

    async def async_step_automation(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            new_options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WATCHDOG_ENABLED,
                    default=self._current(CONF_WATCHDOG_ENABLED, DEFAULT_WATCHDOG_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_RECONCILE_ENABLED,
                    default=self._current(CONF_RECONCILE_ENABLED, DEFAULT_RECONCILE_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_RECONCILE_TIME,
                    default=self._current(CONF_RECONCILE_TIME, DEFAULT_RECONCILE_TIME),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_RECONCILE_TOLERANCE,
                    default=self._current(
                        CONF_RECONCILE_TOLERANCE, DEFAULT_RECONCILE_TOLERANCE
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.01, mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="kWh",
                    )
                ),
                vol.Required(
                    CONF_EXPORT_ENABLED,
                    default=self._current(CONF_EXPORT_ENABLED, False),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EXPORT_FREQUENCY,
                    default=self._current(CONF_EXPORT_FREQUENCY, DEFAULT_EXPORT_FREQUENCY),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=EXPORT_FREQUENCIES,
                        translation_key="export_frequency",
                    )
                ),
                vol.Required(
                    CONF_EXPORT_WEEKDAY,
                    default=self._current(CONF_EXPORT_WEEKDAY, DEFAULT_EXPORT_WEEKDAY),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=str(i), label=day)
                            for i, day in enumerate(WEEKDAYS)
                        ],
                        translation_key="weekday",
                    )
                ),
                vol.Required(
                    CONF_EXPORT_DAY_OF_MONTH,
                    default=self._current(
                        CONF_EXPORT_DAY_OF_MONTH, DEFAULT_EXPORT_DAY_OF_MONTH
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=28, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_EXPORT_TIME,
                    default=self._current(CONF_EXPORT_TIME, DEFAULT_EXPORT_TIME),
                ): selector.TimeSelector(),
            }
        )
        return self.async_show_form(step_id="automation", data_schema=schema)
