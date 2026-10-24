"""Kalender mit allen Messungen und Ereignissen, auch nachträglich eingetragenen."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AquariumConfigEntry, device_info
from .const import EVENT_TYPES, PARAMETERS_BY_KEY, SIGNAL_UPDATED
from .data import KIND_MEASUREMENT

DURATION = timedelta(minutes=15)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AquariumConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AquariumCalendar(entry)])


def _format_number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _to_event(item: dict[str, Any]) -> CalendarEvent:
    start = dt_util.parse_datetime(item["timestamp"])
    if item["kind"] == KIND_MEASUREMENT:
        summary = "Wassertest"
        lines = []
        for key, value in item["values"].items():
            param = PARAMETERS_BY_KEY[key]
            unit = f" {param.unit}" if param.unit else ""
            lines.append(f"{param.name}: {_format_number(value)}{unit}")
    else:
        summary = EVENT_TYPES.get(item["event_type"], item["event_type"])
        lines = []
        if item.get("volume_liters") is not None:
            lines.append(f"Menge: {_format_number(item['volume_liters'])} l")
        if item.get("percent") is not None:
            lines.append(f"Anteil: {_format_number(item['percent'])} %")
    if item.get("note"):
        lines.append(item["note"])
    return CalendarEvent(
        start=start,
        end=start + DURATION,
        summary=summary,
        description="\n".join(lines),
        uid=item["id"],
    )


class AquariumCalendar(CalendarEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Tagebuch"
    _attr_icon = "mdi:fishbowl-outline"

    def __init__(self, entry: AquariumConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_journal"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED.format(self._entry.entry_id),
                self.async_write_ha_state,
            )
        )

    @property
    def _items(self) -> list[dict[str, Any]]:
        return self._entry.runtime_data.log.items

    @property
    def event(self) -> CalendarEvent | None:
        """Laufendes oder nächstes Ereignis; bei einem Tagebuch meist das jüngste."""
        now = dt_util.utcnow()
        for item in self._items:
            event = _to_event(item)
            if event.end_datetime_local >= now:
                return event
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events = []
        for item in self._items:
            event = _to_event(item)
            if event.start_datetime_local < end_date and event.end_datetime_local > start_date:
                events.append(event)
        return events
