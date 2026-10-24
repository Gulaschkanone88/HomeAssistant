"""Meldungen, wenn Wasserwerte mehrfach in Folge außerhalb der Grenzen liegen."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, EVENT_LIMIT_CLEARED, EVENT_LIMIT_EXCEEDED
from .data import AquariumLog

_LOGGER = logging.getLogger(__name__)


def _number(value: float | None) -> str:
    return "–" if value is None else f"{value:g}".replace(".", ",")


def _range_text(violation: dict[str, Any]) -> str:
    unit = f" {violation['unit']}" if violation["unit"] else ""
    low, high = violation["min"], violation["max"]
    if low is not None and high is not None:
        return f"{_number(low)}–{_number(high)}{unit}"
    if high is not None:
        return f"max. {_number(high)}{unit}"
    return f"min. {_number(low)}{unit}"


def _notification_id(entry_id: str, key: str) -> str:
    return f"{DOMAIN}_{entry_id}_{key}"


class AlertManager:
    """Vergleicht den aktuellen Zustand mit den bereits gemeldeten Verletzungen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, log: AquariumLog) -> None:
        self.hass = hass
        self.entry = entry
        self.log = log

    async def async_check(self, keys: list[str]) -> None:
        violations = self.log.violations(keys)
        active = set(self.log.active_alerts)
        new = [key for key in violations if key not in active]
        cleared = [key for key in active if key not in violations]
        if not new and not cleared:
            return

        # Erst den Zustand setzen, dann melden: eine parallel laufende Prüfung meldet so nicht doppelt.
        self.log.active_alerts = sorted(violations)
        await self.log.async_save()

        for key in cleared:
            await self._async_clear(key)
        for key in new:
            await self._async_raise(violations[key])

    async def _async_raise(self, violation: dict[str, Any]) -> None:
        unit = f" {violation['unit']}" if violation["unit"] else ""
        direction = "über" if violation["direction"] == "above" else "unter"
        title = f"{self.entry.title}: {violation['name']} {direction} Grenzwert"
        message = (
            f"{violation['count']} Messungen in Folge außerhalb des Bereichs "
            f"({_range_text(violation)}). Letzter Wert: {_number(violation['value'])}{unit}."
        )
        self.hass.bus.async_fire(
            EVENT_LIMIT_EXCEEDED,
            {"config_entry_id": self.entry.entry_id, "aquarium": self.entry.title, **violation},
        )
        if self.log.settings.get("persistent_notification", True):
            persistent_notification.async_create(
                self.hass,
                message,
                title=title,
                notification_id=_notification_id(self.entry.entry_id, violation["parameter"]),
            )
        await self._async_push(title, message)

    async def _async_clear(self, key: str) -> None:
        self.hass.bus.async_fire(
            EVENT_LIMIT_CLEARED,
            {"config_entry_id": self.entry.entry_id, "aquarium": self.entry.title, "parameter": key},
        )
        persistent_notification.async_dismiss(
            self.hass, _notification_id(self.entry.entry_id, key)
        )

    async def _async_push(self, title: str, message: str) -> None:
        for service in self.log.settings.get("notify_services", []):
            domain, _, name = service.partition(".")
            if domain != "notify" or not self.hass.services.has_service(domain, name):
                _LOGGER.warning("Benachrichtigungsdienst %s nicht gefunden", service)
                continue
            try:
                await self.hass.services.async_call(
                    domain, name, {"title": title, "message": message}, blocking=True
                )
            except Exception:  # noqa: BLE001 - eine fehlerhafte App darf die anderen nicht blockieren
                _LOGGER.exception("Meldung über %s fehlgeschlagen", service)
