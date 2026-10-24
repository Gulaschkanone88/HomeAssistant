"""Warnsensor: an, sobald ein Wasserwert mehrfach in Folge außerhalb der Grenzen liegt."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AquariumConfigEntry, device_info, enabled_parameters
from .const import SIGNAL_UPDATED


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AquariumConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LimitWarningSensor(entry)])


class LimitWarningSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Grenzwertwarnung"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: AquariumConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_limit_warning"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATED.format(self._entry.entry_id), self._handle_update
            )
        )
        self._update()

    @callback
    def _handle_update(self) -> None:
        self._update()
        self.async_write_ha_state()

    @callback
    def _update(self) -> None:
        log = self._entry.runtime_data.log
        violations = log.violations(enabled_parameters(self._entry))
        self._attr_is_on = bool(violations)
        self._attr_extra_state_attributes = {
            "parameters": list(violations),
            "violations": list(violations.values()),
            "alert_count": log.settings["alert_count"],
        }
