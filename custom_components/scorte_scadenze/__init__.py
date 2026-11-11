"""Scorte e Scadenze: manutenzioni periodiche e inventario per Home Assistant."""
from __future__ import annotations

from datetime import date, datetime, time
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CARD_FILENAME,
    CARD_URL,
    DOMAIN,
    PLATFORMS,
    STORAGE_KEY,
    STORAGE_VERSION,
    VERSION,
)
from .manager import Manager
from .websocket import async_register_websocket

type ScorteConfigEntry = ConfigEntry[Manager]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_ITEM_ID = "item_id"
ATTR_QTY = "quantita"
ATTR_DATE = "data"
ATTR_EXPIRY = "scadenza"
ATTR_LOT = "confezione"


def _parse_moment(value: Any) -> datetime:
    """Accetta data o data/ora; una data passata diventa mezzogiorno di quel giorno."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        moment = dt_util.parse_datetime(text)
        if moment is None:
            day = dt_util.parse_date(text)
            if day is None:
                raise vol.Invalid(f"Data non valida: {value}")
            if day == dt_util.now().date():
                return dt_util.now()
            moment = datetime.combine(day, time(12, 0))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return moment


def _parse_day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    day = dt_util.parse_date(str(value).strip())
    if day is None:
        raise vol.Invalid(f"Data non valida: {value}")
    return day


_TARGET = {
    vol.Exclusive(ATTR_ITEM_ID, "articolo"): cv.string,
    vol.Exclusive(ATTR_ENTITY_ID, "articolo"): cv.entity_id,
}
_QTY = vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False))

SCHEMA_DONE = vol.All(
    vol.Schema({**_TARGET, vol.Optional(ATTR_DATE): _parse_day}),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)
SCHEMA_PURCHASE = vol.All(
    vol.Schema(
        {
            **_TARGET,
            vol.Required(ATTR_QTY): _QTY,
            vol.Optional(ATTR_DATE): _parse_moment,
            vol.Optional(ATTR_EXPIRY): _parse_day,
        }
    ),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)
SCHEMA_CONSUME = vol.All(
    vol.Schema({**_TARGET, vol.Required(ATTR_QTY): _QTY}),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)
SCHEMA_SET = vol.All(
    vol.Schema({**_TARGET, vol.Required(ATTR_QTY): vol.All(vol.Coerce(float), vol.Range(min=0))}),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)


SCHEMA_OPEN = vol.All(
    vol.Schema({**_TARGET, vol.Optional(ATTR_LOT): cv.string}),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)
SCHEMA_REMOVE_LOT = vol.All(
    vol.Schema({**_TARGET, vol.Required(ATTR_LOT): cv.string}),
    cv.has_at_least_one_key(ATTR_ITEM_ID, ATTR_ENTITY_ID),
)


def get_manager(hass: HomeAssistant) -> Manager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Scorte e Scadenze non è configurata")
    return entries[0].runtime_data


def _resolve_item(hass: HomeAssistant, call: ServiceCall) -> str:
    if item_id := call.data.get(ATTR_ITEM_ID):
        return item_id
    entity_id = call.data[ATTR_ENTITY_ID]
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or not entry.unique_id:
        raise ServiceValidationError(f"{entity_id} non appartiene a Scorte e Scadenze")
    return entry.unique_id.split("_", 1)[0]


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve la card e la carica in automatico nel frontend."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "frontend" / CARD_FILENAME), True)]
    )
    if "frontend" in hass.config.components:
        add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    else:
        _LOGGER.warning("Frontend non caricato: aggiungi la risorsa %s a mano", CARD_URL)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra card e servizi (una sola volta)."""
    await _async_register_card(hass)

    async def done(call: ServiceCall) -> None:
        await get_manager(hass).async_mark_done(_resolve_item(hass, call), call.data.get(ATTR_DATE))

    async def purchase(call: ServiceCall) -> None:
        await get_manager(hass).async_purchase(
            _resolve_item(hass, call),
            call.data[ATTR_QTY],
            call.data.get(ATTR_DATE),
            call.data.get(ATTR_EXPIRY),
        )

    async def consume(call: ServiceCall) -> None:
        await get_manager(hass).async_consume(_resolve_item(hass, call), call.data[ATTR_QTY])

    async def set_stock(call: ServiceCall) -> None:
        await get_manager(hass).async_set_stock(_resolve_item(hass, call), call.data[ATTR_QTY])

    async def open_lot(call: ServiceCall) -> None:
        await get_manager(hass).async_open(_resolve_item(hass, call), call.data.get(ATTR_LOT))

    async def remove_lot(call: ServiceCall) -> None:
        await get_manager(hass).async_remove_lot(_resolve_item(hass, call), call.data[ATTR_LOT])

    hass.services.async_register(DOMAIN, "apri", open_lot, schema=SCHEMA_OPEN)
    hass.services.async_register(DOMAIN, "togli_confezione", remove_lot, schema=SCHEMA_REMOVE_LOT)
    hass.services.async_register(DOMAIN, "fatto", done, schema=SCHEMA_DONE)
    hass.services.async_register(DOMAIN, "acquisto", purchase, schema=SCHEMA_PURCHASE)
    hass.services.async_register(DOMAIN, "consumo", consume, schema=SCHEMA_CONSUME)
    hass.services.async_register(DOMAIN, "imposta_giacenza", set_stock, schema=SCHEMA_SET)
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ScorteConfigEntry) -> bool:
    manager = Manager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ScorteConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ScorteConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rimuovendo l'integrazione si cancellano anche i dati salvati."""
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ScorteConfigEntry, device: DeviceEntry
) -> bool:
    """Consente di eliminare un articolo direttamente dalla pagina dispositivo."""
    for domain, item_id in device.identifiers:
        if domain == DOMAIN:
            await entry.runtime_data.async_remove(item_id, remove_device=False)
    return True
