"""Aquarium-Tagebuch: Wasserwerte und Pflegeereignisse in Home Assistant erfassen."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_ENTRY_ID,
    ATTR_EVENT_TYPE,
    ATTR_ITEM_ID,
    ATTR_NOTE,
    ATTR_PERCENT,
    ATTR_TIMESTAMP,
    ATTR_VOLUME,
    CARD_FILENAME,
    CONF_PARAMETERS,
    DEFAULT_PARAMETERS,
    DOMAIN,
    EVENT_TYPES,
    FRONTEND_URL,
    PARAMETERS,
    PARAMETERS_BY_KEY,
    SIGNAL_UPDATED,
)
from .data import AquariumLog
from .statistics import async_rebuild_statistics

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_BASE_SCHEMA = {
    vol.Optional(ATTR_ENTRY_ID): cv.string,
    vol.Optional(ATTR_TIMESTAMP): cv.datetime,
    vol.Optional(ATTR_NOTE): cv.string,
}

ADD_MEASUREMENT_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        **{vol.Optional(p.key): vol.Coerce(float) for p in PARAMETERS},
    }
)

ADD_EVENT_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Required(ATTR_EVENT_TYPE): vol.In(list(EVENT_TYPES)),
        vol.Optional(ATTR_VOLUME): vol.Coerce(float),
        vol.Optional(ATTR_PERCENT): vol.All(vol.Coerce(float), vol.Range(0, 100)),
    }
)

UPDATE_ITEM_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Optional(ATTR_EVENT_TYPE): vol.In(list(EVENT_TYPES)),
        vol.Optional(ATTR_VOLUME): vol.Any(None, vol.Coerce(float)),
        vol.Optional(ATTR_PERCENT): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(0, 100))
        ),
        vol.Optional("values"): {vol.In(list(PARAMETERS_BY_KEY)): vol.Any(None, vol.Coerce(float))},
    }
)

DELETE_ITEM_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_ENTRY_ID): cv.string, vol.Required(ATTR_ITEM_ID): cv.string}
)

EXPORT_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


@dataclass
class RuntimeData:
    log: AquariumLog
    slug: str


type AquariumConfigEntry = ConfigEntry[RuntimeData]


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Aquarium-Tagebuch",
        model="Wasserwerte",
    )


def enabled_parameters(entry: ConfigEntry) -> list[str]:
    keys = entry.options.get(CONF_PARAMETERS, DEFAULT_PARAMETERS)
    return [p.key for p in PARAMETERS if p.key in keys]


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> AquariumConfigEntry:
    entries = [
        e for e in hass.config_entries.async_loaded_entries(DOMAIN)
    ]
    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(f"Aquarium {entry_id} nicht gefunden")
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise ServiceValidationError("Kein Aquarium eingerichtet")
    raise ServiceValidationError(
        "Mehrere Aquarien eingerichtet, bitte config_entry_id angeben"
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL, str(Path(__file__).parent / "frontend"), True
            )
        ]
    )
    add_extra_js_url(hass, f"{FRONTEND_URL}/{CARD_FILENAME}?v={integration.version}")

    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_subscribe)
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AquariumConfigEntry) -> bool:
    log = AquariumLog(hass, entry.entry_id)
    await log.async_load()
    entry.runtime_data = RuntimeData(log=log, slug=entry.data["slug"])

    async def _rebuild() -> None:
        # Statistik erst schreiben, wenn der Recorder bereit ist.
        if "recorder" in hass.config.components:
            from homeassistant.components.recorder import get_instance

            await get_instance(hass).async_db_ready
        await async_rebuild_statistics(
            hass, log, entry.runtime_data.slug, entry.title, enabled_parameters(entry)
        )

    @callback
    def _on_update() -> None:
        entry.async_create_background_task(hass, _rebuild(), f"{DOMAIN}_statistics")

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_UPDATED.format(entry.entry_id), _on_update)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Statistik neu aufbauen und offene Karten über geänderte Parameter informieren.
    async_dispatcher_send(hass, SIGNAL_UPDATED.format(entry.entry_id))
    return True


async def _async_reload(hass: HomeAssistant, entry: AquariumConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AquariumConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: AquariumConfigEntry) -> None:
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
    if "recorder" in hass.config.components:
        from homeassistant.components.recorder import get_instance

        from .statistics import statistic_id

        get_instance(hass).async_clear_statistics(
            [statistic_id(entry.data["slug"], key) for key in PARAMETERS_BY_KEY]
        )


def _register_services(hass: HomeAssistant) -> None:
    async def add_measurement(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        values = {k: call.data[k] for k in PARAMETERS_BY_KEY if k in call.data}
        try:
            item = await entry.runtime_data.log.async_add_measurement(
                call.data.get(ATTR_TIMESTAMP), values, call.data.get(ATTR_NOTE)
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"item": item}

    async def add_event(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        item = await entry.runtime_data.log.async_add_event(
            call.data.get(ATTR_TIMESTAMP),
            call.data[ATTR_EVENT_TYPE],
            call.data.get(ATTR_VOLUME),
            call.data.get(ATTR_PERCENT),
            call.data.get(ATTR_NOTE),
        )
        return {"item": item}

    async def update_item(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        changes = {
            k: v
            for k, v in call.data.items()
            if k not in (ATTR_ENTRY_ID, ATTR_ITEM_ID)
        }
        try:
            item = await entry.runtime_data.log.async_update_item(
                call.data[ATTR_ITEM_ID], changes
            )
        except (KeyError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err
        return {"item": item}

    async def delete_item(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        try:
            await entry.runtime_data.log.async_delete_item(call.data[ATTR_ITEM_ID])
        except KeyError as err:
            raise ServiceValidationError(str(err)) from err

    async def export(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        items = entry.runtime_data.log.items
        return {"items": items, "csv": _to_csv(items)}

    optional = SupportsResponse.OPTIONAL
    hass.services.async_register(
        DOMAIN, "add_measurement", add_measurement, ADD_MEASUREMENT_SCHEMA, optional
    )
    hass.services.async_register(DOMAIN, "add_event", add_event, ADD_EVENT_SCHEMA, optional)
    hass.services.async_register(
        DOMAIN, "update_item", update_item, UPDATE_ITEM_SCHEMA, optional
    )
    hass.services.async_register(DOMAIN, "delete_item", delete_item, DELETE_ITEM_SCHEMA)
    hass.services.async_register(
        DOMAIN, "export", export, EXPORT_SCHEMA, SupportsResponse.ONLY
    )


def _to_csv(items: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    keys = [p.key for p in PARAMETERS]
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["zeitpunkt", "art", "ereignis", "liter", "prozent", *keys, "notiz"]
    )
    for item in items:
        values = item.get("values", {})
        writer.writerow(
            [
                item["timestamp"],
                item["kind"],
                EVENT_TYPES.get(item.get("event_type", ""), ""),
                item.get("volume_liters") or "",
                item.get("percent") or "",
                *[values.get(k, "") for k in keys],
                item["note"],
            ]
        )
    return buffer.getvalue()


def _payload(entry: AquariumConfigEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "parameters": [
            {
                "key": p.key,
                "name": p.name,
                "unit": p.unit,
                "step": p.step,
                "max": p.maximum,
            }
            for p in (PARAMETERS_BY_KEY[k] for k in enabled_parameters(entry))
        ],
        "event_types": EVENT_TYPES,
        "items": entry.runtime_data.log.items,
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list"})
@callback
def ws_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    connection.send_result(
        msg["id"],
        [
            {"entry_id": e.entry_id, "title": e.title}
            for e in hass.config_entries.async_loaded_entries(DOMAIN)
        ],
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/subscribe", vol.Optional("entry_id"): str}
)
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Liefert Konfiguration und alle Einträge, danach bei jeder Änderung erneut."""
    try:
        entry = _resolve_entry(hass, msg.get("entry_id"))
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return

    @callback
    def _send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], _payload(entry)))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATED.format(entry.entry_id), _send
    )
    connection.send_result(msg["id"])
    _send()
