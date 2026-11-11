"""Sensori di Scorte e Scadenze."""
from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScorteConfigEntry
from .const import (
    F_DAILY_RATE,
    F_HISTORY,
    F_INTERVAL,
    F_INTERVAL_UNIT,
    F_KIND,
    F_LAST_DONE,
    F_MODE,
    F_REORDER,
    F_THRESHOLD,
    F_UNIT,
    KIND_STOCK,
    KIND_TASK,
    MODE_RATE,
    SIGNAL_UPDATE,
    SUMMARY_ENTITY_ID,
    TITLE,
)
from .entity import ItemEntity, setup_item_platform
from .manager import (
    Manager,
    autonomy_days,
    days_left,
    lot_deadline,
    lots_view,
    next_due,
    stock_level,
)


def _factory(manager: Manager, item_id: str, item: dict[str, Any]):
    if item[F_KIND] != KIND_STOCK:
        return [NextDueSensor(manager, item_id), DaysLeftSensor(manager, item_id)]
    entities = [StockSensor(manager, item_id), ExpirySensor(manager, item_id)]
    if item[F_MODE] == MODE_RATE:
        entities.append(AutonomySensor(manager, item_id))
    return entities


async def async_setup_entry(
    hass: HomeAssistant, entry: ScorteConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_item_platform(
        hass, entry, async_add_entities, _factory,
        extra=[SummarySensor(entry.runtime_data, entry.entry_id)],
    )


class NextDueSensor(ItemEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "prossima_scadenza", "Scadenza")

    @property
    def native_value(self) -> date | None:
        return next_due(self.item) if self.item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        item = self.item or {}
        if item.get(F_KIND) != KIND_TASK:
            return None
        return {
            "ultima_esecuzione": item.get(F_LAST_DONE),
            "intervallo": f"{item.get(F_INTERVAL)} {item.get(F_INTERVAL_UNIT)}",
        }


class DaysLeftSensor(ItemEntity, SensorEntity):
    _attr_native_unit_of_measurement = "giorni"

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "giorni_rimanenti", "Giorni rimanenti")

    @property
    def native_value(self) -> int | None:
        return days_left(self.item) if self.item else None


class StockSensor(ItemEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _unrecorded_attributes = frozenset({"storico", "confezioni"})

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "giacenza", "Giacenza")
        self._attr_native_unit_of_measurement = manager.items[item_id].get(F_UNIT) or None

    @property
    def native_value(self) -> float | None:
        return round(stock_level(self.item), 1) if self.item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self.item or {}
        if not item:
            return {}
        history = item.get(F_HISTORY) or []
        attrs: dict[str, Any] = {
            "soglia": item.get(F_THRESHOLD),
            "quantita_riordino": item.get(F_REORDER),
            "modalita": item.get(F_MODE),
            "ultimo_acquisto": history[-1]["data"] if history else None,
            "storico": history,
            "confezioni": lots_view(item),
        }
        if item.get(F_MODE) == MODE_RATE:
            attrs["consumo_giornaliero"] = item.get(F_DAILY_RATE)
        return attrs


class ExpirySensor(ItemEntity, SensorEntity):
    """Data limite della confezione che scade per prima."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "scadenza_prodotto", "Prima scadenza")

    @property
    def native_value(self) -> date | None:
        item = self.item
        if not item:
            return None
        dates = [d for lot in lots_view(item) if (d := lot_deadline(item, lot))]
        return min(dates) if dates else None


class AutonomySensor(ItemEntity, SensorEntity):
    _attr_native_unit_of_measurement = "giorni"
    _attr_suggested_display_precision = 0

    def __init__(self, manager: Manager, item_id: str) -> None:
        super().__init__(manager, item_id, "autonomia", "Autonomia")

    @property
    def native_value(self) -> float | None:
        if not self.item:
            return None
        value = autonomy_days(self.item)
        return None if value is None else round(value, 1)


class SummarySensor(SensorEntity):
    """Numero di avvisi attivi; negli attributi i dati usati dalla card."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = f"{TITLE} riepilogo"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_native_unit_of_measurement = "avvisi"
    _unrecorded_attributes = frozenset({"articoli", "avvisi"})

    def __init__(self, manager: Manager, entry_id: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry_id}_riepilogo"
        self.entity_id = SUMMARY_ENTITY_ID

    @property
    def native_value(self) -> int:
        return len(self._manager.alerts())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "articoli": self._manager.summary(),
            "avvisi": [
                {"chiave": a.key, "item_id": a.item_id, "gruppo": a.group, "titolo": a.title,
                 "testo": a.text, "urgente": a.urgent, "confezione": a.lot_id}
                for a in self._manager.alerts()
            ],
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state)
        )
