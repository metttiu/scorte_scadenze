"""Gestione dati, calcoli e avvisi per Scorte e Scadenze."""
from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CHECK_INTERVAL_MINUTES,
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_TIME,
    CONF_SHOPPING_ENABLED,
    CONF_SHOPPING_LIST,
    DEFAULT_NOTIFY_TIME,
    DOMAIN,
    EVENT_ALERT,
    EVENT_DIGEST,
    F_ADVANCE,
    F_AFTER_OPEN,
    F_DAILY_RATE,
    F_DUE_DATE,
    F_EXP_ADVANCE,
    F_HISTORY,
    F_ICON,
    F_ID,
    F_IN_LIST,
    F_INITIAL_EXPIRY,
    F_INTERVAL,
    F_INTERVAL_UNIT,
    F_KIND,
    F_LAST_DONE,
    F_LINKED_QTY,
    F_LINKED_STOCK,
    F_LOTS,
    F_MODE,
    F_NAME,
    F_QUANTITY,
    F_REF_DATE,
    F_REORDER,
    F_THRESHOLD,
    F_UNIT,
    HISTORY_MAX,
    KIND_ONCE,
    KIND_STOCK,
    KIND_TASK,
    L_BOUGHT,
    L_EXPIRY,
    L_ID,
    L_OPENED,
    L_QTY,
    MODE_RATE,
    NO_LINK,
    QUIET_FROM,
    SIGNAL_NEW_ITEM,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
    TITLE,
    UNIT_MONTHS,
    UNIT_WEEKS,
)

_LOGGER = logging.getLogger(__name__)
_EPS = 1e-6


# ---------------------------------------------------------------- calcoli puri


def today() -> date:
    return dt_util.now().date()


def add_months(start: date, months: int) -> date:
    """Aggiunge mesi rispettando la fine del mese (31/01 + 1 = 28-29/02)."""
    idx = start.month - 1 + months
    year = start.year + idx // 12
    month = idx % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def next_due(item: dict[str, Any]) -> date:
    """Data della prossima scadenza di un promemoria (ricorrente o singolo)."""
    if item[F_KIND] == KIND_ONCE:
        return date.fromisoformat(item[F_DUE_DATE])
    last = date.fromisoformat(item[F_LAST_DONE])
    value = int(item[F_INTERVAL])
    unit = item[F_INTERVAL_UNIT]
    if unit == UNIT_MONTHS:
        return add_months(last, value)
    if unit == UNIT_WEEKS:
        return last + timedelta(weeks=value)
    return last + timedelta(days=value)


def days_left(item: dict[str, Any]) -> int:
    return (next_due(item) - today()).days


def is_due(item: dict[str, Any]) -> bool:
    return days_left(item) <= int(item.get(F_ADVANCE, 0))


def stock_level(item: dict[str, Any], at: datetime | None = None) -> float:
    """Giacenza attuale (stimata per la modalità a consumo)."""
    quantity = float(item[F_QUANTITY])
    if item[F_MODE] == MODE_RATE:
        ref = dt_util.parse_datetime(item[F_REF_DATE])
        moment = at or dt_util.now()
        elapsed = max(0.0, (moment - ref).total_seconds() / 86400) if ref else 0.0
        quantity -= float(item[F_DAILY_RATE]) * elapsed
    return max(0.0, quantity)


def autonomy_days(item: dict[str, Any]) -> float | None:
    rate = float(item.get(F_DAILY_RATE) or 0)
    if item[F_MODE] != MODE_RATE or rate <= 0:
        return None
    return stock_level(item) / rate


def is_low(item: dict[str, Any]) -> bool:
    return stock_level(item) <= float(item[F_THRESHOLD]) + _EPS


def lot_deadline(item: dict[str, Any], lot: dict[str, Any]) -> date | None:
    """Data entro cui consumare: la più vicina tra scadenza stampata e apertura + N giorni."""
    dates: list[date] = []
    if lot.get(L_EXPIRY):
        dates.append(date.fromisoformat(lot[L_EXPIRY]))
    after_open = int(item.get(F_AFTER_OPEN) or 0)
    if lot.get(L_OPENED) and after_open > 0:
        dates.append(date.fromisoformat(lot[L_OPENED]) + timedelta(days=after_open))
    return min(dates) if dates else None


def _lot_order(item: dict[str, Any]):
    """Ordine di consumo: aperte, poi quelle che scadono prima, poi le più vecchie."""

    def key(lot: dict[str, Any]):
        deadline = lot_deadline(item, lot)
        return (
            0 if lot.get(L_OPENED) else 1,
            deadline or date.max,
            lot.get(L_BOUGHT) or "",
        )

    return key


def lots_view(item: dict[str, Any], at: datetime | None = None) -> list[dict[str, Any]]:
    """Confezioni ancora presenti con la loro quantità residua."""
    lots = sorted(item.get(F_LOTS) or [], key=_lot_order(item))
    excess = sum(float(lot[L_QTY]) for lot in lots) - stock_level(item, at)
    out: list[dict[str, Any]] = []
    for lot in lots:
        qty = float(lot[L_QTY])
        if excess > _EPS:
            used = min(qty, excess)
            excess -= used
            qty -= used
        if qty > _EPS:
            out.append({**lot, L_QTY: qty})
    return out


def lot_alert_days(item: dict[str, Any], lot: dict[str, Any]) -> int | None:
    """Giorni alla data limite se la confezione è da segnalare, altrimenti None."""
    deadline = lot_deadline(item, lot)
    if deadline is None:
        return None
    left = (deadline - today()).days
    return left if left <= int(item.get(F_EXP_ADVANCE, 2)) else None


def fmt_qty(value: float) -> str:
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded).replace(".", ",")


def fmt_day(day: date) -> str:
    return day.strftime("%d/%m")


def when_text(left: int) -> str:
    if left > 1:
        return f"tra {left} giorni"
    if left == 1:
        return "domani"
    if left == 0:
        return "oggi"
    if left == -1:
        return "scaduto ieri"
    return f"scaduto da {-left} giorni"


@dataclass(slots=True)
class Alert:
    """Una cosa che richiede attenzione."""

    key: str
    item_id: str
    group: str  # "fare" | "scadenze" | "spesa"
    title: str
    text: str
    urgent: bool
    lot_id: str | None = None

    @property
    def line(self) -> str:
        return f"{self.title}: {self.text}"


# ------------------------------------------------------------------- manager


class Manager:
    """Contiene gli articoli e coordina persistenza, controlli e avvisi."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.items: dict[str, dict[str, Any]] = {}
        self.meta: dict[str, Any] = {}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._check_lock = asyncio.Lock()

    # ---- persistenza

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.items = data.get("items", {})
        self.meta = data.get("meta", {})
        for item in self.items.values():
            item.pop("notified", None)  # campo della 1.x
            if item[F_KIND] == KIND_STOCK and F_LOTS not in item:
                # Migrazione 1.x: la giacenza esistente diventa una confezione senza scadenza.
                level = stock_level(item)
                item[F_LOTS] = [self._new_lot(level)] if level > _EPS else []
                item[F_QUANTITY] = level
                item[F_REF_DATE] = dt_util.now().isoformat()

    async def _async_save(self) -> None:
        await self._store.async_save({"items": self.items, "meta": self.meta})

    async def _async_commit(self, check: bool = True) -> None:
        await self._async_save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        if check:
            await self.async_check()

    # ---- avvio

    @callback
    def async_start(self) -> None:
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_tick, timedelta(minutes=CHECK_INTERVAL_MINUTES)
            )
        )
        self.entry.async_on_unload(async_at_started(self.hass, self._async_started))

    async def _async_started(self, _hass: HomeAssistant) -> None:
        await self.async_check()

    async def _async_tick(self, _now: datetime) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        await self.async_check()

    # ---- accesso

    def get(self, item_id: str) -> dict[str, Any]:
        item = self.items.get(item_id)
        if item is None:
            raise ServiceValidationError(f"Articolo non trovato: {item_id}")
        return item

    def stocks(self) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i[F_KIND] == KIND_STOCK]

    def _get_stock(self, item_id: str) -> dict[str, Any]:
        item = self.get(item_id)
        if item[F_KIND] != KIND_STOCK:
            raise ServiceValidationError(f"{item[F_NAME]} non è un prodotto")
        return item

    # ---- confezioni

    @staticmethod
    def _new_lot(qty: float, expiry: str | None = None, bought: datetime | None = None) -> dict[str, Any]:
        return {
            L_ID: uuid.uuid4().hex[:8],
            L_QTY: qty,
            L_BOUGHT: (bought or dt_util.now()).isoformat(),
            L_EXPIRY: expiry,
            L_OPENED: None,
        }

    @staticmethod
    def _normalize(item: dict[str, Any]) -> None:
        """Fissa giacenza e confezioni al momento attuale (somma confezioni = giacenza)."""
        level = stock_level(item)
        lots = lots_view(item)
        tracked = sum(lot[L_QTY] for lot in lots)
        if level - tracked > _EPS:
            lots.append(Manager._new_lot(level - tracked))
        item[F_LOTS] = lots
        item[F_QUANTITY] = level
        item[F_REF_DATE] = dt_util.now().isoformat()

    # ---- CRUD

    async def async_create(self, kind: str, data: dict[str, Any]) -> str:
        item_id = uuid.uuid4().hex
        item: dict[str, Any] = {**data, F_ID: item_id, F_KIND: kind}
        if kind == KIND_STOCK:
            qty = float(item.pop(F_QUANTITY, 0) or 0)
            expiry = item.pop(F_INITIAL_EXPIRY, None)
            item[F_QUANTITY] = qty
            item[F_REF_DATE] = dt_util.now().isoformat()
            item[F_LOTS] = [self._new_lot(qty, expiry)] if qty > 0 else []
            item[F_HISTORY] = []
            item[F_IN_LIST] = False
        self.items[item_id] = item
        await self._async_save()
        async_dispatcher_send(self.hass, SIGNAL_NEW_ITEM, item_id)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        await self.async_check()
        return item_id

    async def async_update(self, item_id: str, data: dict[str, Any]) -> None:
        item = self.get(item_id)
        data = dict(data)
        data.pop(F_INITIAL_EXPIRY, None)
        new_qty = data.pop(F_QUANTITY, None)
        old_name = item[F_NAME]
        mode_changed = item[F_KIND] == KIND_STOCK and data.get(F_MODE, item[F_MODE]) != item[F_MODE]

        if item[F_KIND] == KIND_STOCK:
            self._normalize(item)  # fissa la stima prima di cambiare consumo o modalità
        if item.get(F_IN_LIST) and data.get(F_NAME, old_name) != old_name:
            await self._async_shopping_remove(old_name)
            item[F_IN_LIST] = False
        item.update(data)
        if item[F_KIND] == KIND_STOCK and new_qty is not None and abs(float(new_qty) - item[F_QUANTITY]) > 0.05:
            self._set_level(item, float(new_qty))

        if item[F_NAME] != old_name:
            registry = dr.async_get(self.hass)
            if device := registry.async_get_device(identifiers={(DOMAIN, item_id)}):
                registry.async_update_device(device.id, name=item[F_NAME])
        await self._async_commit()
        if mode_changed:
            # Cambia l'insieme delle entità (sensore Autonomia): ricarica.
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def async_remove(self, item_id: str, remove_device: bool = True) -> None:
        item = self.items.pop(item_id, None)
        if item is None:
            return
        for other in self.items.values():
            if other.get(F_LINKED_STOCK) == item_id:
                other[F_LINKED_STOCK] = NO_LINK
        if item.get(F_IN_LIST):
            await self._async_shopping_remove(item[F_NAME])
        if remove_device:
            registry = dr.async_get(self.hass)
            if device := registry.async_get_device(identifiers={(DOMAIN, item_id)}):
                registry.async_remove_device(device.id)
        await self._async_commit(check=False)

    # ---- operazioni promemoria

    async def async_mark_done(self, item_id: str, when: date | None = None) -> None:
        item = self.get(item_id)
        if item[F_KIND] == KIND_ONCE:
            # Una scadenza singola, una volta fatta, non serve più.
            self.hass.bus.async_fire(EVENT_ALERT, {"item_id": item_id, "nome": item[F_NAME], "tipo": "completata"})
            await self.async_remove(item_id)
            return
        if item[F_KIND] != KIND_TASK:
            raise ServiceValidationError(f"{item[F_NAME]} non è un promemoria")
        item[F_LAST_DONE] = (when or today()).isoformat()
        linked = item.get(F_LINKED_STOCK)
        qty = float(item.get(F_LINKED_QTY) or 0)
        if linked and linked != NO_LINK and linked in self.items and qty > 0:
            self._consume(self.items[linked], qty)
        await self._async_commit()

    # ---- operazioni prodotti

    async def async_purchase(
        self, item_id: str, qty: float, when: datetime | None = None, expiry: date | None = None
    ) -> None:
        item = self._get_stock(item_id)
        now = dt_util.now()
        when = min(when or now, now)
        self._normalize(item)
        level = item[F_QUANTITY]
        if item[F_MODE] == MODE_RATE and when < now:
            # Quanto acquistato in passato è già stato in parte consumato.
            rate = float(item[F_DAILY_RATE])
            if level > _EPS:
                add = qty
            else:
                add = max(0.0, qty - rate * (now - when).total_seconds() / 86400)
        else:
            add = qty
        if add > _EPS:
            item[F_LOTS].append(self._new_lot(add, expiry.isoformat() if expiry else None, when))
            item[F_QUANTITY] = level + add
        history = item.setdefault(F_HISTORY, [])
        history.append({"data": when.isoformat(), "quantita": qty, "scadenza": expiry.isoformat() if expiry else None})
        history.sort(key=lambda h: h["data"])
        del history[:-HISTORY_MAX]
        await self._async_commit()

    async def async_consume(self, item_id: str, qty: float) -> None:
        self._consume(self._get_stock(item_id), qty)
        await self._async_commit()

    async def async_set_stock(self, item_id: str, qty: float) -> None:
        item = self._get_stock(item_id)
        self._normalize(item)
        self._set_level(item, qty)
        await self._async_commit()

    async def async_open(self, item_id: str, lot_id: str | None = None) -> None:
        """Segna come aperta una confezione (1 unità); per default quella che scade prima."""
        item = self._get_stock(item_id)
        self._normalize(item)
        candidates = [lot for lot in item[F_LOTS] if not lot.get(L_OPENED)]
        if lot_id:
            candidates = [lot for lot in candidates if lot[L_ID] == lot_id]
        if not candidates:
            raise ServiceValidationError(f"Nessuna confezione chiusa di {item[F_NAME]} da aprire")
        lot = sorted(candidates, key=_lot_order(item))[0]
        if lot[L_QTY] > 1 + _EPS:
            lot[L_QTY] -= 1
            opened = {**lot, L_ID: uuid.uuid4().hex[:8], L_QTY: 1.0}
            item[F_LOTS].append(opened)
            lot = opened
        lot[L_OPENED] = today().isoformat()
        await self._async_commit()

    async def async_remove_lot(self, item_id: str, lot_id: str) -> None:
        """Confezione finita o buttata: la toglie dalla giacenza."""
        item = self._get_stock(item_id)
        self._normalize(item)
        lot = next((lot for lot in item[F_LOTS] if lot[L_ID] == lot_id), None)
        if lot is None:
            raise ServiceValidationError("Confezione non trovata")
        item[F_LOTS].remove(lot)
        item[F_QUANTITY] = max(0.0, item[F_QUANTITY] - lot[L_QTY])
        await self._async_commit()

    def _consume(self, item: dict[str, Any], qty: float) -> None:
        self._normalize(item)
        self._set_level(item, item[F_QUANTITY] - qty)

    def _set_level(self, item: dict[str, Any], qty: float) -> None:
        """Imposta la giacenza: i cali escono dalle confezioni in ordine di consumo."""
        item[F_QUANTITY] = max(0.0, qty)
        item[F_REF_DATE] = dt_util.now().isoformat()
        self._normalize(item)

    # ---- avvisi

    def alerts(self) -> list[Alert]:
        out: list[Alert] = []
        for item in self.items.values():
            name = item[F_NAME]
            if item[F_KIND] in (KIND_TASK, KIND_ONCE):
                if is_due(item):
                    left = days_left(item)
                    text = when_text(left) if left < 0 else f"da fare {when_text(left)}"
                    out.append(Alert(f"{item[F_ID]}:fare", item[F_ID], "fare", name, text, left <= 0))
                continue
            for lot in lots_view(item):
                left = lot_alert_days(item, lot)
                if left is None:
                    continue
                title = name + (" (aperta)" if lot.get(L_OPENED) else "")
                if lot[L_QTY] > 1 + _EPS:
                    title += f" ×{fmt_qty(lot[L_QTY])}"
                deadline = lot_deadline(item, lot)
                if left < 0:
                    text = f"scaduta il {fmt_day(deadline)}"
                elif left == 0:
                    text = "da consumare oggi"
                else:
                    text = f"da consumare entro {fmt_day(deadline)} ({when_text(left)})"
                out.append(
                    Alert(f"{item[F_ID]}:{lot[L_ID]}", item[F_ID], "scadenze", title, text, left <= 0, lot[L_ID])
                )
            if is_low(item):
                level = stock_level(item)
                unit = item.get(F_UNIT, "")
                text = "esaurito" if level <= _EPS else f"restano circa {fmt_qty(level)} {unit}".rstrip()
                autonomy = autonomy_days(item)
                if autonomy is not None and level > _EPS:
                    text += f" ({fmt_qty(autonomy)} giorni)"
                out.append(Alert(f"{item[F_ID]}:spesa", item[F_ID], "spesa", name, text, level <= _EPS))
        return out

    def _times(self) -> tuple[time, time]:
        start = dt_util.parse_time(self.entry.options.get(CONF_NOTIFY_TIME, DEFAULT_NOTIFY_TIME)) or time(9)
        return start, dt_util.parse_time(QUIET_FROM) or time(22)

    async def async_check(self) -> None:
        """Riepilogo giornaliero, avvisi urgenti immediati e lista della spesa."""
        async with self._check_lock:
            alerts = self.alerts()
            keys = {a.key for a in alerts}
            now = dt_util.now()
            start, quiet = self._times()
            sent: set[str] = set(self.meta.get("urgenti_inviati", [])) & keys
            changed = sent != set(self.meta.get("urgenti_inviati", []))

            if now.time() >= start and self.meta.get("riepilogo") != now.date().isoformat():
                if alerts:
                    await self._async_send_digest(alerts)
                sent |= {a.key for a in alerts if a.urgent}
                self.meta["riepilogo"] = now.date().isoformat()
                changed = True
            elif start <= now.time() < quiet:
                for alert in alerts:
                    if alert.urgent and alert.key not in sent:
                        await self._async_send_urgent(alert)
                        sent.add(alert.key)
                        changed = True
            self.meta["urgenti_inviati"] = sorted(sent)

            if await self._async_sync_shopping(alerts):
                changed = True
            if changed:
                await self._async_save()
                async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def _async_send_digest(self, alerts: list[Alert]) -> None:
        sections = (
            ("fare", "⏰ Da fare"),
            ("scadenze", "⌛ Scadenze prodotti"),
            ("spesa", "🛒 Da comprare"),
        )
        parts = []
        for group, label in sections:
            lines = [f"• {a.line}" for a in alerts if a.group == group]
            if lines:
                parts.append(label + "\n" + "\n".join(lines))
        message = "\n\n".join(parts)
        self.hass.bus.async_fire(
            EVENT_DIGEST,
            {"messaggio": message, "avvisi": [{"item_id": a.item_id, "gruppo": a.group, "testo": a.line} for a in alerts]},
        )
        await self._async_notify_all(f"{TITLE}: {len(alerts)} da gestire", message)

    async def _async_send_urgent(self, alert: Alert) -> None:
        icon = {"fare": "⏰", "scadenze": "⌛", "spesa": "🛒"}[alert.group]
        message = f"{icon} {alert.line}"
        self.hass.bus.async_fire(
            EVENT_ALERT,
            {"item_id": alert.item_id, "nome": alert.title, "tipo": alert.group, "messaggio": message,
             "confezione": alert.lot_id},
        )
        await self._async_notify_all(TITLE, message)

    async def _async_notify_all(self, title: str, message: str) -> None:
        for target in self.entry.options.get(CONF_NOTIFY_TARGETS, []):
            await self._async_notify(target.strip(), title, message)

    async def _async_notify(self, target: str, title: str, message: str) -> None:
        if not target:
            return
        try:
            if target.startswith("notify.") and self.hass.states.get(target) is not None:
                await self.hass.services.async_call(
                    "notify", "send_message",
                    {"entity_id": target, "title": title, "message": message}, blocking=True,
                )
                return
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", target
            if not self.hass.services.has_service(domain, service):
                _LOGGER.warning("Servizio di notifica non trovato: %s", target)
                return
            await self.hass.services.async_call(
                domain, service, {"title": title, "message": message}, blocking=True
            )
        except Exception:  # noqa: BLE001 - una notifica fallita non deve bloccare il resto
            _LOGGER.exception("Invio notifica fallito verso %s", target)

    # ---- lista della spesa

    async def _async_sync_shopping(self, alerts: list[Alert]) -> bool:
        low = {a.item_id for a in alerts if a.group == "spesa"}
        enabled = self.entry.options.get(CONF_SHOPPING_ENABLED, True)
        changed = False
        for item in self.stocks():
            if item[F_ID] in low and enabled and not item.get(F_IN_LIST):
                if await self._async_shopping_add(item[F_NAME]):
                    item[F_IN_LIST] = True
                    changed = True
            elif item[F_ID] not in low and item.get(F_IN_LIST):
                await self._async_shopping_remove(item[F_NAME])
                item[F_IN_LIST] = False
                changed = True
        return changed

    def _shopping_entity(self) -> str | None:
        entity_id = self.entry.options.get(CONF_SHOPPING_LIST)
        if not entity_id or self.hass.states.get(entity_id) is None:
            return None
        return entity_id

    async def _async_shopping_items(self, entity_id: str) -> list[str]:
        result = await self.hass.services.async_call(
            "todo", "get_items", {"entity_id": entity_id, "status": ["needs_action"]},
            blocking=True, return_response=True,
        )
        items = (result or {}).get(entity_id, {}).get("items", [])
        return [i.get("summary", "") for i in items]

    async def _async_shopping_add(self, name: str) -> bool:
        entity_id = self._shopping_entity()
        if entity_id is None:
            return False
        try:
            existing = {s.casefold() for s in await self._async_shopping_items(entity_id)}
            if name.casefold() not in existing:
                await self.hass.services.async_call(
                    "todo", "add_item", {"entity_id": entity_id, "item": name}, blocking=True
                )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Impossibile aggiungere %s alla lista della spesa", name)
            return False
        return True

    async def _async_shopping_remove(self, name: str) -> None:
        entity_id = self._shopping_entity()
        if entity_id is None:
            return
        try:
            existing = await self._async_shopping_items(entity_id)
            matches = [s for s in existing if s.casefold() == name.casefold()]
            if matches:
                await self.hass.services.async_call(
                    "todo", "remove_item", {"entity_id": entity_id, "item": matches}, blocking=True
                )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Impossibile rimuovere %s dalla lista della spesa", name)

    # ---- riepilogo per la card

    def summary(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.items.values():
            base: dict[str, Any] = {
                "id": item[F_ID],
                "nome": item[F_NAME],
                "tipo": item[F_KIND],
                "icona": item.get(F_ICON),
            }
            if item[F_KIND] in (KIND_TASK, KIND_ONCE):
                base.update(
                    prossima=next_due(item).isoformat(),
                    giorni=days_left(item),
                    da_fare=is_due(item),
                    preavviso=int(item.get(F_ADVANCE, 0)),
                )
                if item[F_KIND] == KIND_TASK:
                    base.update(
                        ultima=item[F_LAST_DONE],
                        intervallo=int(item[F_INTERVAL]),
                        unita_intervallo=item[F_INTERVAL_UNIT],
                        scorta_collegata=item.get(F_LINKED_STOCK, NO_LINK),
                        quantita_collegata=float(item.get(F_LINKED_QTY) or 0),
                    )
            else:
                autonomy = autonomy_days(item)
                lots = []
                for lot in lots_view(item):
                    deadline = lot_deadline(item, lot)
                    lots.append(
                        {
                            "id": lot[L_ID],
                            "qta": round(lot[L_QTY], 2),
                            "scadenza": lot.get(L_EXPIRY),
                            "aperta": lot.get(L_OPENED),
                            "entro": deadline.isoformat() if deadline else None,
                            "giorni": (deadline - today()).days if deadline else None,
                            "avviso": lot_alert_days(item, lot) is not None,
                        }
                    )
                history = item.get(F_HISTORY) or []
                base.update(
                    modalita=item[F_MODE],
                    giacenza=round(stock_level(item), 1),
                    unita=item.get(F_UNIT, ""),
                    soglia=float(item[F_THRESHOLD]),
                    riordino=float(item.get(F_REORDER) or 1),
                    consumo=float(item.get(F_DAILY_RATE) or 0),
                    dopo_apertura=int(item.get(F_AFTER_OPEN) or 0),
                    preavviso_scadenza=int(item.get(F_EXP_ADVANCE, 2)),
                    autonomia=None if autonomy is None else round(autonomy, 1),
                    sotto_soglia=is_low(item),
                    confezioni=lots,
                    acquisti=history[-5:][::-1],
                )
            out.append(base)
        out.sort(key=lambda i: i["nome"].casefold())
        return out
