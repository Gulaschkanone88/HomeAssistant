"""Lesende Schnittstellen für Auswertungen: REST-API und LLM-API (für den MCP-Server von HA)."""

from __future__ import annotations

import csv
from datetime import datetime
import io
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonObjectType

from . import analysis
from .const import DOMAIN, EVENT_TYPES, PARAMETERS, PARAMETERS_BY_KEY

LLM_API_ID = DOMAIN


def _parse_time(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        date = dt_util.parse_date(value)
        if date is None:
            raise ValueError(f"{name}: ungültiges Datum '{value}'")
        parsed = datetime.combine(date, datetime.min.time())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed)


def _parse_days(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    days = int(value)
    if days < 0:
        raise ValueError("days darf nicht negativ sein")
    return days


def _find_entry(hass: HomeAssistant, ref: str | None):
    """Becken über entry_id oder Namen finden; bei nur einem Becken darf ref fehlen."""
    from . import _resolve_entry

    if ref:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if ref in (entry.entry_id, entry.title) or ref.lower() == entry.title.lower():
                return entry
    return _resolve_entry(hass, ref)


def _context(entry) -> tuple[Any, list[str]]:
    from . import enabled_parameters

    return entry.runtime_data.log, enabled_parameters(entry)


def _measurements_csv(rows: list[dict[str, Any]], keys: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["zeitpunkt", *keys, "notiz"])
    for row in rows:
        writer.writerow([row["timestamp"], *[row["values"].get(k, "") for k in keys], row["note"]])
    return buffer.getvalue()


# ---------------------------------------------------------------- REST

class _AquariumView(HomeAssistantView):
    requires_auth = True

    async def get(self, request: web.Request, **kwargs: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        try:
            entry = _find_entry(hass, request.query.get("aquarium"))
            log, keys = _context(entry)
            return self.respond(entry, log, keys, request.query, **kwargs)
        except (ValueError, ServiceValidationError, HomeAssistantError) as err:
            return self.json_message(str(err), status_code=400)

    def respond(self, entry, log, keys, query, **kwargs) -> web.Response:
        raise NotImplementedError


class SummaryView(_AquariumView):
    """GET /api/aquarium_log/summary?days=90"""

    url = f"/api/{DOMAIN}/summary"
    name = f"api:{DOMAIN}:summary"

    def respond(self, entry, log, keys, query, **kwargs):
        days = _parse_days(query.get("days", 90))
        return self.json({"aquarium": entry.title, **analysis.summary(log, keys, days)})


class MeasurementsView(_AquariumView):
    """GET /api/aquarium_log/measurements?start=2026-01-01&end=…&parameter=no3&format=csv"""

    url = f"/api/{DOMAIN}/measurements"
    name = f"api:{DOMAIN}:measurements"

    def respond(self, entry, log, keys, query, **kwargs):
        if parameter := query.get("parameter"):
            if parameter not in PARAMETERS_BY_KEY:
                raise ValueError(f"Unbekannter Wasserwert: {parameter}")
            keys = [parameter]
        rows = analysis.measurements(
            log, keys, _parse_time(query.get("start"), "start"), _parse_time(query.get("end"), "end")
        )
        if query.get("format") == "csv":
            return web.Response(
                text=_measurements_csv(rows, keys),
                content_type="text/csv",
                charset="utf-8",
            )
        return self.json({"aquarium": entry.title, "parameters": keys, "measurements": rows})


class EventsView(_AquariumView):
    """GET /api/aquarium_log/events?start=…&end=…&event_type=water_change"""

    url = f"/api/{DOMAIN}/events"
    name = f"api:{DOMAIN}:events"

    def respond(self, entry, log, keys, query, **kwargs):
        event_type = query.get("event_type")
        if event_type and event_type not in EVENT_TYPES:
            raise ValueError(f"Unbekannte Ereignisart: {event_type}")
        rows = analysis.events(
            log,
            _parse_time(query.get("start"), "start"),
            _parse_time(query.get("end"), "end"),
            event_type,
        )
        return self.json({"aquarium": entry.title, "events": rows})


class AnalysisView(_AquariumView):
    """GET /api/aquarium_log/analysis/no3?days=180"""

    url = f"/api/{DOMAIN}/analysis/{{parameter}}"
    name = f"api:{DOMAIN}:analysis"

    def respond(self, entry, log, keys, query, parameter: str = "", **kwargs):
        if parameter not in PARAMETERS_BY_KEY:
            raise ValueError(f"Unbekannter Wasserwert: {parameter}")
        days = _parse_days(query.get("days"))
        return self.json({"aquarium": entry.title, **analysis.analyze(log, parameter, days)})


@callback
def async_register_views(hass: HomeAssistant) -> None:
    for view in (SummaryView, MeasurementsView, EventsView, AnalysisView):
        hass.http.register_view(view())


# ---------------------------------------------------------------- LLM-API

_AQUARIUM = vol.Optional("aquarium", description="Name des Beckens; nur nötig, wenn mehrere eingerichtet sind")
_DAYS = vol.Optional("days", description="Zeitraum in Tagen rückwärts ab heute; 0 oder leer = alles")
_PARAMETER_KEYS = [p.key for p in PARAMETERS]


class _AquariumTool(llm.Tool):
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        args = tool_input.tool_args
        try:
            entry = _find_entry(hass, args.get("aquarium"))
            log, keys = _context(entry)
            return {"aquarium": entry.title, **self.run(log, keys, args)}
        except (ValueError, ServiceValidationError, HomeAssistantError) as err:
            return {"error": str(err)}

    def run(self, log, keys, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class SummaryTool(_AquariumTool):
    name = "aquarium_summary"
    description = (
        "Überblick über das Aquarium: jüngster Wert, Grenzen, Status, Mittel/Min/Max, Trend pro Woche "
        "und Anteil außerhalb der Grenzen je Wasserwert, dazu Wasserwechsel-Statistik und aktive Warnungen. "
        "Guter Startpunkt für jede Analyse."
    )
    parameters = vol.Schema({_AQUARIUM: str, _DAYS: vol.All(int, vol.Range(min=0))})

    def run(self, log, keys, args):
        return analysis.summary(log, keys, _parse_days(args.get("days", 90)))


class MeasurementsTool(_AquariumTool):
    name = "aquarium_measurements"
    description = (
        "Rohdaten der Wassertests im Zeitraum, älteste zuerst. Zeitpunkte in UTC (ISO 8601). "
        "Optional auf einen Wasserwert beschränken."
    )
    parameters = vol.Schema(
        {
            _AQUARIUM: str,
            vol.Optional("parameter", description="Schlüssel des Wasserwerts"): vol.In(_PARAMETER_KEYS),
            vol.Optional("start", description="Beginn, ISO-Datum oder -Zeitpunkt"): str,
            vol.Optional("end", description="Ende, ISO-Datum oder -Zeitpunkt"): str,
            vol.Optional("limit", description="Höchstens so viele jüngste Messungen"): vol.All(int, vol.Range(min=1)),
        }
    )

    def run(self, log, keys, args):
        if args.get("parameter"):
            keys = [args["parameter"]]
        rows = analysis.measurements(
            log,
            keys,
            _parse_time(args.get("start"), "start"),
            _parse_time(args.get("end"), "end"),
            args.get("limit"),
        )
        units = {k: PARAMETERS_BY_KEY[k].unit for k in keys}
        return {"units": units, "measurements": rows}


class EventsTool(_AquariumTool):
    name = "aquarium_events"
    description = (
        "Pflegeereignisse im Zeitraum (Wasserwechsel mit Litern und Prozent, Düngung, Filterreinigung, "
        "Besatz, Medikamente usw.), älteste zuerst."
    )
    parameters = vol.Schema(
        {
            _AQUARIUM: str,
            vol.Optional("event_type", description="Nur diese Ereignisart"): vol.In(list(EVENT_TYPES)),
            vol.Optional("start", description="Beginn, ISO-Datum oder -Zeitpunkt"): str,
            vol.Optional("end", description="Ende, ISO-Datum oder -Zeitpunkt"): str,
        }
    )

    def run(self, log, keys, args):
        return {
            "events": analysis.events(
                log,
                _parse_time(args.get("start"), "start"),
                _parse_time(args.get("end"), "end"),
                args.get("event_type"),
            )
        }


class AnalyzeTool(_AquariumTool):
    name = "aquarium_analyze"
    description = (
        "Tiefere Auswertung eines Wasserwerts: Statistik, Wirkung jedes Wasserwechsels (vorher/nachher), "
        "durchschnittliche Veränderung pro Tag zwischen den Wasserwechseln und Prognose, in wie vielen Tagen "
        "die Grenze erreicht wird. Enthält die Messreihe."
    )
    parameters = vol.Schema(
        {
            _AQUARIUM: str,
            vol.Required("parameter", description="Schlüssel des Wasserwerts"): vol.In(_PARAMETER_KEYS),
            _DAYS: vol.All(int, vol.Range(min=0)),
        }
    )

    def run(self, log, keys, args):
        return analysis.analyze(log, args["parameter"], _parse_days(args.get("days")))


API_PROMPT = (
    "Das Aquarium-Tagebuch enthält manuell mit einem Tropftest-Koffer gemessene Wasserwerte und "
    "dokumentierte Pflegeereignisse. Schlüssel der Wasserwerte: "
    + ", ".join(f"{p.key} = {p.name}{f' [{p.unit}]' if p.unit else ''}" for p in PARAMETERS)
    + ". Die Grenzen (limit_min/limit_max) hat der Nutzer selbst festgelegt. Tropftests haben eine grobe "
    "Farbskala; kleine Schwankungen sind Messungenauigkeit, keine Entwicklung. Alle Zeitpunkte sind UTC. "
    "Beginne Auswertungen mit aquarium_summary und nutze aquarium_analyze für einzelne Werte."
)


class AquariumLLMAPI(llm.API):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=LLM_API_ID, name="Aquarium-Tagebuch")

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=[SummaryTool(), MeasurementsTool(), EventsTool(), AnalyzeTool()],
        )


@callback
def async_register_llm_api(hass: HomeAssistant) -> None:
    llm.async_register_api(hass, AquariumLLMAPI(hass))
