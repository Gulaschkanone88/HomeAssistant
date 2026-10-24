"""Datenhaltung des Aquarium-Tagebuchs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PARAMETERS_BY_KEY, SIGNAL_UPDATED, STORAGE_VERSION

KIND_MEASUREMENT = "measurement"
KIND_EVENT = "event"


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return dt_util.utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(value)


class AquariumLog:
    """Hält Messungen und Ereignisse eines Beckens und speichert sie in .storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.items: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.items = (data or {}).get("items", [])
        self._sort()

    def _sort(self) -> None:
        self.items.sort(key=lambda item: item["timestamp"])

    async def _async_commit(self) -> None:
        self._sort()
        await self._store.async_save({"items": self.items})
        async_dispatcher_send(self.hass, SIGNAL_UPDATED.format(self.entry_id))

    @staticmethod
    def _clean_values(values: dict[str, Any]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, value in values.items():
            if key not in PARAMETERS_BY_KEY:
                raise ValueError(f"Unbekannter Wasserwert: {key}")
            if value is None or value == "":
                continue
            cleaned[key] = float(value)
        return cleaned

    async def async_add_measurement(
        self, timestamp: datetime | None, values: dict[str, Any], note: str | None
    ) -> dict[str, Any]:
        cleaned = self._clean_values(values)
        if not cleaned:
            raise ValueError("Mindestens ein Wasserwert muss angegeben werden")
        item = {
            "id": uuid.uuid4().hex,
            "kind": KIND_MEASUREMENT,
            "timestamp": _as_utc(timestamp).isoformat(),
            "values": cleaned,
            "note": note or "",
        }
        self.items.append(item)
        await self._async_commit()
        return item

    async def async_add_event(
        self,
        timestamp: datetime | None,
        event_type: str,
        volume_liters: float | None,
        percent: float | None,
        note: str | None,
    ) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex,
            "kind": KIND_EVENT,
            "timestamp": _as_utc(timestamp).isoformat(),
            "event_type": event_type,
            "volume_liters": volume_liters,
            "percent": percent,
            "note": note or "",
        }
        self.items.append(item)
        await self._async_commit()
        return item

    async def async_update_item(
        self, item_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        item = self.get_item(item_id)
        if "timestamp" in changes:
            item["timestamp"] = _as_utc(changes["timestamp"]).isoformat()
        if "note" in changes:
            item["note"] = changes["note"] or ""
        if item["kind"] == KIND_MEASUREMENT and "values" in changes:
            cleaned = self._clean_values(changes["values"])
            if not cleaned:
                raise ValueError("Mindestens ein Wasserwert muss angegeben werden")
            item["values"] = cleaned
        if item["kind"] == KIND_EVENT:
            for key in ("event_type", "volume_liters", "percent"):
                if key in changes:
                    item[key] = changes[key]
        await self._async_commit()
        return item

    async def async_delete_item(self, item_id: str) -> None:
        self.items.remove(self.get_item(item_id))
        await self._async_commit()

    def get_item(self, item_id: str) -> dict[str, Any]:
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise KeyError(f"Eintrag {item_id} nicht gefunden")

    @callback
    def latest_value(self, key: str) -> tuple[float, str] | None:
        """Jüngster Messwert eines Parameters nach Messzeitpunkt, nicht nach Eingabezeit."""
        for item in reversed(self.items):
            if item["kind"] == KIND_MEASUREMENT and key in item["values"]:
                return item["values"][key], item["timestamp"]
        return None

    @callback
    def latest_event(self, event_type: str) -> dict[str, Any] | None:
        for item in reversed(self.items):
            if item["kind"] == KIND_EVENT and item["event_type"] == event_type:
                return item
        return None

    @callback
    def measurements(self, key: str) -> list[tuple[datetime, float]]:
        return [
            (dt_util.parse_datetime(item["timestamp"]), item["values"][key])
            for item in self.items
            if item["kind"] == KIND_MEASUREMENT and key in item["values"]
        ]
