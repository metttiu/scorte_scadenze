"""Entità base legata a un articolo e aggiunta dinamica delle entità."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    F_ICON,
    F_KIND,
    F_NAME,
    KIND_ONCE,
    KIND_TASK,
    SIGNAL_NEW_ITEM,
    SIGNAL_UPDATE,
    TITLE,
)
from .manager import Manager

_MODELS = {KIND_TASK: "Promemoria ricorrente", KIND_ONCE: "Scadenza singola"}


@callback
def setup_item_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[Manager, str, dict[str, Any]], Iterable[Entity]],
    extra: Iterable[Entity] = (),
) -> None:
    """Crea le entità degli articoli esistenti e di quelli aggiunti in seguito."""
    manager: Manager = entry.runtime_data
    entities = list(extra)
    for item_id, item in manager.items.items():
        entities.extend(factory(manager, item_id, item))
    async_add_entities(entities)

    @callback
    def _new_item(item_id: str) -> None:
        if item := manager.items.get(item_id):
            async_add_entities(list(factory(manager, item_id, item)))

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_ITEM, _new_item))


class ItemEntity(Entity):
    """Entità di un singolo articolo."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: Manager, item_id: str, key: str, name: str) -> None:
        self._manager = manager
        self._item_id = item_id
        item = manager.items[item_id]
        self._attr_unique_id = f"{item_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item_id)},
            name=item[F_NAME],
            manufacturer=TITLE,
            model=_MODELS.get(item[F_KIND], "Prodotto"),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def item(self) -> dict[str, Any] | None:
        return self._manager.items.get(self._item_id)

    @property
    def available(self) -> bool:
        return self.item is not None

    @property
    def icon(self) -> str | None:
        item = self.item
        return item.get(F_ICON) if item else None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state)
        )
