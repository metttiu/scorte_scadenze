"""Comandi websocket usati dalla card per creare, modificare ed eliminare articoli."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, KINDS
from .schemas import ItemValidationError, validate_item


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_save)
    websocket_api.async_register_command(hass, ws_delete)


def _manager(hass: HomeAssistant):
    from . import get_manager  # import ritardato per evitare cicli

    return get_manager(hass)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/salva",
        vol.Optional("item_id"): str,
        vol.Required("tipo"): vol.In(KINDS),
        vol.Required("dati"): dict,
    }
)
@websocket_api.async_response
async def ws_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        manager = _manager(hass)
        data = validate_item(msg["tipo"], msg["dati"])
        if item_id := msg.get("item_id"):
            if manager.get(item_id)["kind"] != msg["tipo"]:
                connection.send_error(msg["id"], "tipo_non_valido", "Il tipo di un articolo non si può cambiare")
                return
            await manager.async_update(item_id, data)
        else:
            item_id = await manager.async_create(msg["tipo"], data)
    except ItemValidationError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "errore", str(err))
        return
    connection.send_result(msg["id"], {"item_id": item_id})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/elimina", vol.Required("item_id"): str}
)
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        manager = _manager(hass)
        manager.get(msg["item_id"])
        await manager.async_remove(msg["item_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "errore", str(err))
        return
    connection.send_result(msg["id"], {})
