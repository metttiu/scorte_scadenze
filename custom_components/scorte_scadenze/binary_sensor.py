"""Sensori binari: da fare / da acquistare / in scadenza."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScorteConfigEntry
from .const import F_KIND, KIND_STOCK
from .entity import ItemEntity, setup_item_platform
from .manager import Manager, is_due, is_low, lot_alert_days, lots_view


def _factory(manager: Manager, item_id: str, item: dict[str, Any]):
    if item[F_KIND] == KIND_STOCK:
        return [LowBinarySensor(manager, item_id), ExpiringBinarySensor(manager, item_id)]
    return [DueBinarySensor(manager, item_id)]


async def async_setup_entry(
    hass: HomeAssistant, entry: ScorteConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_item_platform(hass, entry, async_add_entities, _factory)


class DueBinarySensor(ItemEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "da_fare", "Da fare")

    @property
    def is_on(self) -> bool | None:
        return is_due(self.item) if self.item else None


class LowBinarySensor(ItemEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "da_acquistare", "Da acquistare")

    @property
    def is_on(self) -> bool | None:
        return is_low(self.item) if self.item else None


class ExpiringBinarySensor(ItemEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "in_scadenza", "In scadenza")

    @property
    def icon(self) -> str:
        return "mdi:timer-sand"

    @property
    def is_on(self) -> bool | None:
        item = self.item
        if not item:
            return None
        return any(lot_alert_days(item, lot) is not None for lot in lots_view(item))
