"""Lista nativa con tutto ciò che richiede attenzione."""
from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScorteConfigEntry
from .const import F_REORDER, F_UNIT, SIGNAL_UPDATE, TITLE
from .manager import Manager, fmt_qty, next_due

_HINT = {
    "fare": "Spunta quando l'hai fatto.",
    "scadenze": "Spunta quando la confezione è finita o buttata.",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ScorteConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AlertsTodo(entry.runtime_data, entry.entry_id)])


class AlertsTodo(TodoListEntity):
    """Spuntare: promemoria → fatto; confezione → tolta; scorta → acquisto di riordino."""

    _attr_should_poll = False
    _attr_name = TITLE
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, manager: Manager, entry_id: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry_id}_da_fare"

    @property
    def todo_items(self) -> list[TodoItem]:
        out: list[TodoItem] = []
        for alert in self._manager.alerts():
            item = self._manager.items[alert.item_id]
            if alert.group == "spesa":
                unit = item.get(F_UNIT, "")
                hint = f"Spunta per registrare l'acquisto di {fmt_qty(float(item.get(F_REORDER) or 1))} {unit}".rstrip() + "."
            else:
                hint = _HINT[alert.group]
            out.append(
                TodoItem(
                    summary=alert.title,
                    uid=alert.key,
                    status=TodoItemStatus.NEEDS_ACTION,
                    due=next_due(item) if alert.group == "fare" else None,
                    description=f"{alert.text[:1].upper()}{alert.text[1:]}. {hint}",
                )
            )
        return out

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.status != TodoItemStatus.COMPLETED or not item.uid:
            raise ServiceValidationError("Puoi solo spuntare le voci come completate")
        alert = next((a for a in self._manager.alerts() if a.key == item.uid), None)
        if alert is None:
            return
        if alert.group == "fare":
            await self._manager.async_mark_done(alert.item_id)
        elif alert.group == "scadenze" and alert.lot_id:
            await self._manager.async_remove_lot(alert.item_id, alert.lot_id)
        else:
            stored = self._manager.get(alert.item_id)
            await self._manager.async_purchase(alert.item_id, float(stored.get(F_REORDER) or 1))

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state)
        )
