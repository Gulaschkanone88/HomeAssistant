"""Konstanten für das Aquarium-Tagebuch."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "aquarium_log"
STORAGE_VERSION = 1

CONF_PARAMETERS = "parameters"

SIGNAL_UPDATED = f"{DOMAIN}_updated_{{}}"

FRONTEND_URL = f"/{DOMAIN}_static"
CARD_FILENAME = "aquarium-log-card.js"

ATTR_ENTRY_ID = "config_entry_id"
ATTR_TIMESTAMP = "timestamp"
ATTR_NOTE = "note"
ATTR_EVENT_TYPE = "event_type"
ATTR_VOLUME = "volume_liters"
ATTR_PERCENT = "percent"
ATTR_ITEM_ID = "item_id"


@dataclass(frozen=True)
class Parameter:
    """Ein messbarer Wasserwert."""

    key: str
    name: str
    unit: str | None
    icon: str
    step: float
    maximum: float


# Reihenfolge = Reihenfolge in Formular und Diagramm.
PARAMETERS: tuple[Parameter, ...] = (
    Parameter("ph", "pH-Wert", None, "mdi:ph", 0.1, 14),
    Parameter("kh", "Karbonathärte (KH)", "°dH", "mdi:water-opacity", 1, 50),
    Parameter("gh", "Gesamthärte (GH)", "°dH", "mdi:water-opacity", 1, 50),
    Parameter("no2", "Nitrit (NO₂)", "mg/l", "mdi:flask-outline", 0.05, 10),
    Parameter("no3", "Nitrat (NO₃)", "mg/l", "mdi:flask-outline", 1, 500),
    Parameter("cl", "Chlor (Cl)", "mg/l", "mdi:flask-outline", 0.01, 10),
    Parameter("nh4", "Ammonium (NH₄)", "mg/l", "mdi:flask-outline", 0.05, 20),
    Parameter("po4", "Phosphat (PO₄)", "mg/l", "mdi:flask-outline", 0.05, 20),
    Parameter("fe", "Eisen (Fe)", "mg/l", "mdi:flask-outline", 0.01, 10),
    Parameter("cu", "Kupfer (Cu)", "mg/l", "mdi:flask-outline", 0.01, 10),
    Parameter("co2", "Kohlendioxid (CO₂)", "mg/l", "mdi:molecule-co2", 1, 200),
    Parameter("o2", "Sauerstoff (O₂)", "mg/l", "mdi:gas-cylinder", 0.5, 30),
    Parameter("temperature", "Temperatur", "°C", "mdi:thermometer", 0.1, 45),
    Parameter("conductivity", "Leitwert", "µS/cm", "mdi:flash-outline", 1, 5000),
)

PARAMETERS_BY_KEY: dict[str, Parameter] = {p.key: p for p in PARAMETERS}

# Tests der sera aqua-test box (+Cl); weitere Werte lassen sich in den Optionen zuschalten.
DEFAULT_PARAMETERS: list[str] = ["ph", "kh", "gh", "no2", "no3", "cl"]

EVENT_TYPES: dict[str, str] = {
    "water_change": "Wasserwechsel",
    "fertilizer": "Düngung",
    "conditioner": "Wasseraufbereiter",
    "filter": "Filterreinigung",
    "cleaning": "Beckenpflege",
    "plants": "Pflanzen",
    "livestock": "Besatz",
    "medication": "Medikament",
    "technology": "Technik",
    "other": "Sonstiges",
}
