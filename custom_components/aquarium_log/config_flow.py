"""Einrichtung und Optionen des Aquarium-Tagebuchs."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from .const import CONF_PARAMETERS, DEFAULT_PARAMETERS, DOMAIN, PARAMETERS


def _parameter_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=p.key, label=f"{p.name} [{p.unit}]" if p.unit else p.name
                )
                for p in PARAMETERS
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


class AquariumLogConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            slug = slugify(user_input[CONF_NAME])
            if not slug:
                errors[CONF_NAME] = "invalid_name"
            else:
                await self.async_set_unique_id(slug)
                self._abort_if_unique_id_configured()
                if not user_input[CONF_PARAMETERS]:
                    errors[CONF_PARAMETERS] = "no_parameters"
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={"slug": slug},
                        options={CONF_PARAMETERS: user_input[CONF_PARAMETERS]},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Aquarium"): str,
                    vol.Required(
                        CONF_PARAMETERS, default=DEFAULT_PARAMETERS
                    ): _parameter_selector(),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AquariumLogOptionsFlow()


class AquariumLogOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_PARAMETERS]:
                return self.async_create_entry(data=user_input)
            errors[CONF_PARAMETERS] = "no_parameters"

        current = self.config_entry.options.get(CONF_PARAMETERS, DEFAULT_PARAMETERS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_PARAMETERS, default=current): _parameter_selector()}
            ),
            errors=errors,
        )
