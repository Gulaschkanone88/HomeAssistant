"""Auswertungen über Messungen und Ereignisse, gemeinsam genutzt von REST-API, Dienst und LLM-API."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from homeassistant.util import dt as dt_util

from .const import EVENT_TYPES, PARAMETERS_BY_KEY
from .data import KIND_EVENT, KIND_MEASUREMENT, AquariumLog

DAY = 86400

# Fenster, in denen eine Messung als "vor" bzw. "nach" einem Wasserwechsel zählt.
BEFORE_WINDOW = timedelta(days=7)
AFTER_WINDOW = timedelta(days=3)


def _ts(item: dict[str, Any]) -> datetime:
    return dt_util.parse_datetime(item["timestamp"])


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _in_period(item: dict[str, Any], start: datetime | None, end: datetime | None) -> bool:
    when = _ts(item)
    return (start is None or when >= start) and (end is None or when <= end)


def _slope_per_day(points: list[tuple[datetime, float]]) -> float | None:
    """Steigung der Ausgleichsgeraden in Einheit pro Tag."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(when - t0).total_seconds() / DAY for when, _ in points]
    ys = [value for _, value in points]
    mx, my = mean(xs), mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


def _status(log: AquariumLog, key: str, value: float | None) -> str:
    low, high = log.limit(key)
    if value is None:
        return "no_data"
    if low is None and high is None:
        return "no_limit"
    if high is not None and value > high:
        return "above"
    if low is not None and value < low:
        return "below"
    return "ok"


def period(days: int | None) -> tuple[datetime | None, datetime]:
    end = dt_util.utcnow()
    return (end - timedelta(days=days) if days else None), end


def measurements(
    log: AquariumLog,
    keys: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = [
        {
            "timestamp": item["timestamp"],
            "values": {k: v for k, v in item["values"].items() if k in keys},
            "note": item["note"],
        }
        for item in log.items
        if item["kind"] == KIND_MEASUREMENT and _in_period(item, start, end)
    ]
    rows = [row for row in rows if row["values"]]
    return rows[-limit:] if limit else rows


def events(
    log: AquariumLog,
    start: datetime | None = None,
    end: datetime | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": item["timestamp"],
            "event_type": item["event_type"],
            "event_name": EVENT_TYPES.get(item["event_type"], item["event_type"]),
            "volume_liters": item.get("volume_liters"),
            "percent": item.get("percent"),
            "note": item["note"],
        }
        for item in log.items
        if item["kind"] == KIND_EVENT
        and (event_type is None or item["event_type"] == event_type)
        and _in_period(item, start, end)
    ]


def _series(log: AquariumLog, key: str, start: datetime | None, end: datetime | None):
    return [(when, value) for when, value in log.measurements(key) if
            (start is None or when >= start) and (end is None or when <= end)]


def _parameter_stats(
    log: AquariumLog, key: str, start: datetime | None, end: datetime | None
) -> dict[str, Any]:
    param = PARAMETERS_BY_KEY[key]
    low, high = log.limit(key)
    all_points = log.measurements(key)
    points = _series(log, key, start, end)
    latest = all_points[-1] if all_points else None
    values = [value for _, value in points]
    out = [v for v in values if (low is not None and v < low) or (high is not None and v > high)]
    slope = _slope_per_day(points)
    return {
        "name": param.name,
        "unit": param.unit,
        "limit_min": low,
        "limit_max": high,
        "latest": latest[1] if latest else None,
        "latest_at": latest[0].isoformat() if latest else None,
        "status": _status(log, key, latest[1] if latest else None),
        "count": len(values),
        "mean": _round(mean(values)) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "trend_per_week": _round(slope * 7) if slope is not None else None,
        "share_out_of_range": _round(len(out) / len(values), 2) if values else None,
    }


def _water_changes(log: AquariumLog) -> list[dict[str, Any]]:
    return [
        item for item in log.items
        if item["kind"] == KIND_EVENT and item["event_type"] == "water_change"
    ]


def summary(log: AquariumLog, keys: list[str], days: int | None) -> dict[str, Any]:
    """Überblick: Stand, Statistik und Trend je Wert, Wasserwechsel, aktive Warnungen."""
    start, end = period(days)
    changes = _water_changes(log)
    last = changes[-1] if changes else None
    intervals = [
        (_ts(b) - _ts(a)).total_seconds() / DAY for a, b in zip(changes, changes[1:], strict=False)
    ]
    in_period = [c for c in changes if _in_period(c, start, end)]
    return {
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat(), "days": days},
        "parameters": {key: _parameter_stats(log, key, start, end) for key in keys},
        "water_changes": {
            "count_in_period": len(in_period),
            "liters_in_period": sum(c.get("volume_liters") or 0 for c in in_period),
            "last": last["timestamp"] if last else None,
            "days_since_last": _round((end - _ts(last)).total_seconds() / DAY, 1) if last else None,
            "last_volume_liters": last.get("volume_liters") if last else None,
            "last_percent": last.get("percent") if last else None,
            "average_interval_days": _round(mean(intervals), 1) if intervals else None,
        },
        "measurements_in_period": len(measurements(log, keys, start, end)),
        "active_warnings": list(log.violations(keys).values()),
        "alert_count": log.settings["alert_count"],
        "open_notes": log.notes_for(include_done=False, limit=10),
    }


def analyze(log: AquariumLog, key: str, days: int | None) -> dict[str, Any]:
    """Tiefere Auswertung eines Werts: Wirkung der Wasserwechsel, Anstieg dazwischen, Prognose."""
    start, end = period(days)
    stats = _parameter_stats(log, key, start, end)
    all_points = log.measurements(key)
    changes = [c for c in _water_changes(log) if _in_period(c, start, end)]

    effects = []
    for change in changes:
        when = _ts(change)
        before = [p for p in all_points if when - BEFORE_WINDOW <= p[0] <= when]
        after = [p for p in all_points if when < p[0] <= when + AFTER_WINDOW]
        if not before or not after:
            continue
        b, a = before[-1][1], after[0][1]
        effects.append(
            {
                "water_change": change["timestamp"],
                "percent": change.get("percent"),
                "volume_liters": change.get("volume_liters"),
                "before": b,
                "after": a,
                "change": _round(a - b),
                "change_percent": _round((a - b) / b * 100, 1) if b else None,
            }
        )

    # Veränderung zwischen zwei Wasserwechseln (bzw. seit dem letzten bis heute).
    all_changes = [_ts(c) for c in _water_changes(log)]
    bounds = [*all_changes, end]
    rates = []
    for a, b in zip(bounds, bounds[1:], strict=False):
        segment = [p for p in all_points if a < p[0] < b]
        slope = _slope_per_day(segment)
        if slope is not None and (start is None or b >= start):
            rates.append({"from": a.isoformat(), "to": b.isoformat(), "per_day": _round(slope), "points": len(segment)})

    avg_rate = mean(r["per_day"] for r in rates) if rates else None
    forecast = None
    high = stats["limit_max"]
    low = stats["limit_min"]
    latest = stats["latest"]
    if avg_rate and latest is not None:
        if avg_rate > 0 and high is not None and latest < high:
            forecast = {"limit": "max", "days_until_limit": _round((high - latest) / avg_rate, 1)}
        elif avg_rate < 0 and low is not None and latest > low:
            forecast = {"limit": "min", "days_until_limit": _round((latest - low) / -avg_rate, 1)}

    return {
        "parameter": key,
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat(), "days": days},
        "statistics": stats,
        "water_change_effect": {
            "samples": effects,
            "average_change": _round(mean(e["change"] for e in effects)) if effects else None,
            "average_change_percent": _round(
                mean(e["change_percent"] for e in effects if e["change_percent"] is not None), 1
            ) if any(e["change_percent"] is not None for e in effects) else None,
            "method": "letzte Messung bis 7 Tage vor und erste Messung bis 3 Tage nach dem Wasserwechsel",
        },
        "change_between_water_changes": {
            "segments": rates,
            "average_per_day": _round(avg_rate),
        },
        "forecast": forecast,
        "notes": log.notes_for(key, limit=10),
        "series": [{"timestamp": when.isoformat(), "value": value} for when, value in _series(log, key, start, end)],
    }
