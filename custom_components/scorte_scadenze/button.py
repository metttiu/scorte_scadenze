"""Pulsanti: segna come fatto / registra riordino."""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScorteConfigEntry
from .const import F_KIND, F_REORDER, KIND_STOCK
from .entity import ItemEntity, setup_item_platform
from .manager import Manager


def _factory(manager: Manager, item_id: str, item: dict[str, Any]):
    if item[F_KIND] == KIND_STOCK:
        return [ReorderButton(manager, item_id)]
    return [DoneButton(manager, item_id)]


async def async_setup_entry(
    hass: HomeAssistant, entry: ScorteConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_item_platform(hass, entry, async_add_entities, _factory)


class DoneButton(ItemEntity, ButtonEntity):
    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "fatto", "Segna come fatto")

    @property
    def icon(self) -> str:
        return "mdi:check-circle-outline"

    async def async_press(self) -> None:
        await self._manager.async_mark_done(self._item_id)


class ReorderButton(ItemEntity, ButtonEntity):
    """Registra un acquisto della quantità di riordino predefinita."""

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "riordino", "Registra riordino")

    @property
    def icon(self) -> str:
        return "mdi:cart-check"

    async def async_press(self) -> None:
        qty = float((self.item or {}).get(F_REORDER) or 1)
        await self._manager.async_purchase(self._item_id, qty)
