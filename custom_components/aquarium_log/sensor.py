"""Sensoren mit dem jeweils jüngsten Messwert und dem letzten Wasserwechsel."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AquariumConfigEntry, device_info, enabled_parameters
from .const import PARAMETERS_BY_KEY, SIGNAL_UPDATED, Parameter
from .data import AquariumLog
from .statistics import statistic_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AquariumConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entities: list[SensorEntity] = [
        AquariumParameterSensor(entry, PARAMETERS_BY_KEY[key])
        for key in enabled_parameters(entry)
    ]
    entities.append(LastWaterChangeSensor(entry))
    async_add_entities(entities)


class AquariumEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: AquariumConfigEntry) -> None:
        self._entry = entry
        self._log: AquariumLog = entry.runtime_data.log
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED.format(self._entry.entry_id),
                self._handle_update,
            )
        )
        self._update_from_log()

    @callback
    def _handle_update(self) -> None:
        self._update_from_log()
        self.async_write_ha_state()

    @callback
    def _update_from_log(self) -> None:
        raise NotImplementedError


class AquariumParameterSensor(AquariumEntity):
    """Zustand = jüngster Messwert. Kein state_class: den Langzeitverlauf mit
    nachgetragenen Werten liefert die externe Statistik aquarium_log:<becken>_<wert>."""

    def __init__(self, entry: AquariumConfigEntry, param: Parameter) -> None:
        super().__init__(entry)
        self._param = param
        self._attr_unique_id = f"{entry.entry_id}_{param.key}"
        self._attr_name = param.name
        self._attr_icon = param.icon
        self._attr_native_unit_of_measurement = param.unit
        self._attr_suggested_display_precision = 2 if param.step < 0.1 else 1 if param.step < 1 else 0

    @callback
    def _update_from_log(self) -> None:
        latest = self._log.latest_value(self._param.key)
        attrs: dict[str, Any] = {
            "statistic_id": statistic_id(self._entry.runtime_data.slug, self._param.key)
        }
        if latest is None:
            self._attr_native_value = None
        else:
            self._attr_native_value = latest[0]
            attrs["measured_at"] = latest[1]
        self._attr_extra_state_attributes = attrs


class LastWaterChangeSensor(AquariumEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:water-sync"

    def __init__(self, entry: AquariumConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_last_water_change"
        self._attr_name = "Letzter Wasserwechsel"

    @callback
    def _update_from_log(self) -> None:
        event = self._log.latest_event("water_change")
        if event is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        self._attr_native_value = dt_util.parse_datetime(event["timestamp"])
        self._attr_extra_state_attributes = {
            "volume_liters": event.get("volume_liters"),
            "percent": event.get("percent"),
            "note": event.get("note"),
        }
