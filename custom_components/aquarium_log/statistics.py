"""Schreibt die Messreihen als externe Langzeitstatistik in den Recorder.

Externe Statistiken dürfen beliebige Zeitpunkte in der Vergangenheit haben. So erscheinen
auch nachgetragene Werte an der richtigen Stelle im Verlauf (Statistik-Diagramm-Karte).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import logging

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PARAMETERS_BY_KEY
from .data import AquariumLog

_LOGGER = logging.getLogger(__name__)


def statistic_id(slug: str, key: str) -> str:
    return f"{DOMAIN}:{slug}_{key}"


def _metadata(slug: str, title: str, key: str) -> StatisticMetaData:
    param = PARAMETERS_BY_KEY[key]
    return {
        "mean_type": StatisticMeanType.ARITHMETIC,
        "has_sum": False,
        "name": f"{title} {param.name}",
        "source": DOMAIN,
        "statistic_id": statistic_id(slug, key),
        # Keine Einheitenumrechnung, Werte bleiben in der Einheit des Testkoffers.
        "unit_class": None,
        "unit_of_measurement": param.unit,
    }


def _hourly(points: list[tuple[datetime, float]]) -> list[StatisticData]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for when, value in points:
        buckets[when.replace(minute=0, second=0, microsecond=0)].append(value)
    return [
        {
            "start": start,
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }
        for start, values in sorted(buckets.items())
    ]


async def async_rebuild_statistics(
    hass: HomeAssistant, log: AquariumLog, slug: str, title: str, keys: list[str]
) -> None:
    """Löscht die Statistik der Parameter und schreibt sie aus den Messungen neu."""
    if "recorder" not in hass.config.components:
        return

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )

    instance = get_instance(hass)
    ids = [statistic_id(slug, key) for key in PARAMETERS_BY_KEY]
    # Löschen und Neuschreiben laufen nacheinander in der Recorder-Warteschlange.
    instance.async_clear_statistics(ids)
    for key in keys:
        rows = _hourly(log.measurements(key))
        if not rows:
            continue
        try:
            async_add_external_statistics(hass, _metadata(slug, title, key), rows)
        except Exception:  # noqa: BLE001 - Statistik ist Zusatz, das Tagebuch läuft weiter
            _LOGGER.exception("Statistik für %s konnte nicht geschrieben werden", key)
