"""Datenhaltung des Aquarium-Tagebuchs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_ALERT_COUNT,
    DEFAULT_LIMITS,
    DOMAIN,
    PARAMETERS_BY_KEY,
    SIGNAL_UPDATED,
    STORAGE_VERSION,
)

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
        self.settings: dict[str, Any] = {}
        # Parameter, für die bereits eine Meldung verschickt wurde; überdauert Neustarts.
        self.active_alerts: list[str] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.items = data.get("items", [])
        self.settings = {
            "limits": {key: dict(value) for key, value in DEFAULT_LIMITS.items()},
            "alert_count": DEFAULT_ALERT_COUNT,
            "persistent_notification": True,
            "notify_services": [],
            **data.get("settings", {}),
        }
        self.active_alerts = data.get("active_alerts", [])
        self._sort()

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "items": self.items,
                "settings": self.settings,
                "active_alerts": self.active_alerts,
            }
        )

    def _sort(self) -> None:
        self.items.sort(key=lambda item: item["timestamp"])

    async def _async_commit(self) -> None:
        self._sort()
        await self.async_save()
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

    async def async_update_settings(self, changes: dict[str, Any]) -> None:
        if "limits" in changes:
            limits = {key: dict(value) for key, value in self.settings["limits"].items()}
            for key, value in changes["limits"].items():
                if key not in PARAMETERS_BY_KEY:
                    raise ValueError(f"Unbekannter Wasserwert: {key}")
                low, high = value.get("min"), value.get("max")
                if low is not None and high is not None and low > high:
                    raise ValueError(
                        f"{PARAMETERS_BY_KEY[key].name}: Minimum liegt über dem Maximum"
                    )
                limits[key] = {"min": low, "max": high}
            self.settings["limits"] = limits
        for key in ("alert_count", "persistent_notification", "notify_services"):
            if key in changes:
                self.settings[key] = changes[key]
        await self._async_commit()

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

    @callback
    def limit(self, key: str) -> tuple[float | None, float | None]:
        value = self.settings["limits"].get(key) or {}
        return value.get("min"), value.get("max")

    @callback
    def violations(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        """Parameter, deren jüngste Messungen alle außerhalb der Grenzen liegen.

        Gezählt wird von der neuesten Messung rückwärts, bis eine im Bereich liegt.
        Ab alert_count Messungen in Folge gilt der Wert als verletzt.
        """
        needed = max(1, int(self.settings["alert_count"]))
        result: dict[str, dict[str, Any]] = {}
        for key in keys:
            low, high = self.limit(key)
            if low is None and high is None:
                continue
            streak: list[tuple[str, float]] = []
            for item in reversed(self.items):
                if item["kind"] != KIND_MEASUREMENT or key not in item["values"]:
                    continue
                value = item["values"][key]
                if (low is not None and value < low) or (high is not None and value > high):
                    streak.append((item["timestamp"], value))
                else:
                    break
            if len(streak) < needed:
                continue
            latest = streak[0][1]
            result[key] = {
                "parameter": key,
                "name": PARAMETERS_BY_KEY[key].name,
                "unit": PARAMETERS_BY_KEY[key].unit,
                "value": latest,
                "min": low,
                "max": high,
                "direction": "above" if high is not None and latest > high else "below",
                "count": len(streak),
                "since": streak[-1][0],
            }
        return result
