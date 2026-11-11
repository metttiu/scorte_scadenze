"""Configurazione e gestione articoli dal menu Configura (alternativa alla card)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_TIME,
    CONF_SHOPPING_ENABLED,
    CONF_SHOPPING_LIST,
    DEFAULT_NOTIFY_TIME,
    DEFAULT_ONCE_ICON,
    DEFAULT_SHOPPING_LIST,
    DEFAULT_STOCK_ICON,
    DEFAULT_TASK_ICON,
    DOMAIN,
    F_ADVANCE,
    F_AFTER_OPEN,
    F_DAILY_RATE,
    F_DUE_DATE,
    F_EXP_ADVANCE,
    F_ICON,
    F_INITIAL_EXPIRY,
    F_INTERVAL,
    F_INTERVAL_UNIT,
    F_KIND,
    F_LAST_DONE,
    F_LINKED_QTY,
    F_LINKED_STOCK,
    F_MODE,
    F_NAME,
    F_QUANTITY,
    F_REORDER,
    F_THRESHOLD,
    F_UNIT,
    KIND_ONCE,
    KIND_STOCK,
    KIND_TASK,
    MODE_PIECES,
    MODE_RATE,
    NO_LINK,
    TITLE,
    UNIT_DAYS,
    UNIT_MONTHS,
    UNIT_WEEKS,
)
from .manager import Manager, stock_level, today
from .schemas import ItemValidationError, validate_item

ITEM_SELECT = "articolo"
ITEMS_SELECT = "articoli"
_KIND_LABEL = {KIND_TASK: "promemoria", KIND_ONCE: "scadenza", KIND_STOCK: "prodotto"}


def _number(minimum: float, maximum: float, step: float | str = 1, unit: str | None = None):
    config = sel.NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=sel.NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return sel.NumberSelector(config)


def _select(options: list[tuple[str, str]], mode=sel.SelectSelectorMode.DROPDOWN):
    return sel.SelectSelector(
        sel.SelectSelectorConfig(
            options=[sel.SelectOptionDict(value=v, label=l) for v, l in options], mode=mode
        )
    )


def _settings_schema(opts: dict[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Optional(CONF_NOTIFY_TARGETS, default=opts.get(CONF_NOTIFY_TARGETS, [])): sel.TextSelector(
            sel.TextSelectorConfig(multiple=True)
        ),
        vol.Required(CONF_NOTIFY_TIME, default=opts.get(CONF_NOTIFY_TIME, DEFAULT_NOTIFY_TIME)): sel.TimeSelector(),
        vol.Required(CONF_SHOPPING_ENABLED, default=opts.get(CONF_SHOPPING_ENABLED, True)): sel.BooleanSelector(),
    }
    shopping = opts.get(CONF_SHOPPING_LIST, DEFAULT_SHOPPING_LIST)
    key = vol.Optional(CONF_SHOPPING_LIST, default=shopping) if shopping else vol.Optional(CONF_SHOPPING_LIST)
    schema[key] = sel.EntitySelector(sel.EntitySelectorConfig(domain="todo"))
    return vol.Schema(schema)


def _clean_settings(data: dict[str, Any]) -> dict[str, Any]:
    targets = [t.strip() for t in data.get(CONF_NOTIFY_TARGETS, []) if t and t.strip()]
    return {**data, CONF_NOTIFY_TARGETS: targets}


def _task_schema(d: dict[str, Any], stocks: list[dict[str, Any]]) -> vol.Schema:
    links = [(NO_LINK, "Nessuna")] + [(s["id"], s[F_NAME]) for s in stocks]
    return vol.Schema(
        {
            vol.Required(F_NAME, default=d.get(F_NAME, "")): sel.TextSelector(),
            vol.Required(F_INTERVAL, default=d.get(F_INTERVAL, 30)): _number(1, 3650),
            vol.Required(F_INTERVAL_UNIT, default=d.get(F_INTERVAL_UNIT, UNIT_DAYS)): _select(
                [(UNIT_DAYS, "Giorni"), (UNIT_WEEKS, "Settimane"), (UNIT_MONTHS, "Mesi")]
            ),
            vol.Required(F_LAST_DONE, default=d.get(F_LAST_DONE, today().isoformat())): sel.DateSelector(),
            vol.Required(F_ADVANCE, default=d.get(F_ADVANCE, 0)): _number(0, 365, unit="giorni"),
            vol.Required(F_LINKED_STOCK, default=d.get(F_LINKED_STOCK, NO_LINK)): _select(links),
            vol.Required(F_LINKED_QTY, default=d.get(F_LINKED_QTY, 1)): _number(0, 1000, "any"),
            vol.Required(F_ICON, default=d.get(F_ICON, DEFAULT_TASK_ICON)): sel.IconSelector(),
        }
    )


def _once_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(F_NAME, default=d.get(F_NAME, "")): sel.TextSelector(),
            vol.Required(F_DUE_DATE, default=d.get(F_DUE_DATE, today().isoformat())): sel.DateSelector(),
            vol.Required(F_ADVANCE, default=d.get(F_ADVANCE, 7)): _number(0, 365, unit="giorni"),
            vol.Required(F_ICON, default=d.get(F_ICON, DEFAULT_ONCE_ICON)): sel.IconSelector(),
        }
    )


def _stock_schema(d: dict[str, Any], new: bool) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(F_NAME, default=d.get(F_NAME, "")): sel.TextSelector(),
        vol.Required(F_MODE, default=d.get(F_MODE, MODE_PIECES)): _select(
            [(MODE_PIECES, "A pezzi (scalo io)"), (MODE_RATE, "A consumo medio giornaliero")],
            sel.SelectSelectorMode.LIST,
        ),
        vol.Optional(F_UNIT, default=d.get(F_UNIT, "pz")): sel.TextSelector(),
        vol.Required(F_QUANTITY, default=d.get(F_QUANTITY, 0)): _number(0, 1_000_000, "any"),
        vol.Required(F_DAILY_RATE, default=d.get(F_DAILY_RATE, 0)): _number(0, 10_000, "any"),
        vol.Required(F_THRESHOLD, default=d.get(F_THRESHOLD, 1)): _number(0, 1_000_000, "any"),
        vol.Required(F_REORDER, default=d.get(F_REORDER, 1)): _number(0, 1_000_000, "any"),
        vol.Required(F_AFTER_OPEN, default=d.get(F_AFTER_OPEN, 0)): _number(0, 3650, unit="giorni"),
        vol.Required(F_EXP_ADVANCE, default=d.get(F_EXP_ADVANCE, 2)): _number(0, 365, unit="giorni"),
    }
    if new:
        schema[vol.Optional(F_INITIAL_EXPIRY)] = sel.DateSelector()
    schema[vol.Required(F_ICON, default=d.get(F_ICON, DEFAULT_STOCK_ICON))] = sel.IconSelector()
    return vol.Schema(schema)


class ScorteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Prima configurazione: notifiche e lista della spesa."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=_clean_settings(user_input))
        return self.async_show_form(step_id="user", data_schema=_settings_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> ScorteOptionsFlow:
        return ScorteOptionsFlow()


class ScorteOptionsFlow(OptionsFlow):
    """Menu per aggiungere, modificare ed eliminare articoli."""

    def __init__(self) -> None:
        self._edit_id: str | None = None

    @property
    def _manager(self) -> Manager:
        return self.config_entry.runtime_data

    def _done(self) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.config_entry.options))

    def _item_options(self) -> list[tuple[str, str]]:
        items = sorted(self._manager.items.values(), key=lambda i: i[F_NAME].casefold())
        return [(i["id"], f"{i[F_NAME]} ({_KIND_LABEL[i[F_KIND]]})") for i in items]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "aggiungi_scadenza", "aggiungi_singola", "aggiungi_scorta",
                "modifica", "elimina", "impostazioni",
            ],
        )

    async def async_step_impostazioni(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean_settings(user_input))
        return self.async_show_form(step_id="impostazioni", data_schema=_settings_schema(dict(self.config_entry.options)))

    # ---- aggiunta / modifica condivise

    async def _save(self, kind: str, step_id: str, schema: vol.Schema, user_input, placeholders=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = validate_item(kind, user_input)
            except ItemValidationError as err:
                errors[err.field if err.field in schema.schema else "base"] = err.code
            else:
                if self._edit_id:
                    await self._manager.async_update(self._edit_id, data)
                else:
                    await self._manager.async_create(kind, data)
                return self._done()
        return self.async_show_form(
            step_id=step_id, data_schema=schema, errors=errors, description_placeholders=placeholders
        )

    async def async_step_aggiungi_scadenza(self, user_input=None) -> ConfigFlowResult:
        return await self._save(KIND_TASK, "aggiungi_scadenza",
                                _task_schema(user_input or {}, self._manager.stocks()), user_input)

    async def async_step_aggiungi_singola(self, user_input=None) -> ConfigFlowResult:
        return await self._save(KIND_ONCE, "aggiungi_singola", _once_schema(user_input or {}), user_input)

    async def async_step_aggiungi_scorta(self, user_input=None) -> ConfigFlowResult:
        return await self._save(KIND_STOCK, "aggiungi_scorta", _stock_schema(user_input or {}, True), user_input)

    async def async_step_modifica(self, user_input=None) -> ConfigFlowResult:
        if not self._manager.items:
            return self.async_abort(reason="nessun_articolo")
        if user_input is not None:
            self._edit_id = user_input[ITEM_SELECT]
            kind = self._manager.get(self._edit_id)[F_KIND]
            step = {KIND_TASK: self.async_step_modifica_scadenza, KIND_ONCE: self.async_step_modifica_singola,
                    KIND_STOCK: self.async_step_modifica_scorta}[kind]
            return await step()
        return self.async_show_form(
            step_id="modifica",
            data_schema=vol.Schema({vol.Required(ITEM_SELECT): _select(self._item_options())}),
        )

    async def async_step_modifica_scadenza(self, user_input=None) -> ConfigFlowResult:
        item = self._manager.get(self._edit_id)
        stocks = [s for s in self._manager.stocks() if s["id"] != self._edit_id]
        return await self._save(KIND_TASK, "modifica_scadenza", _task_schema(user_input or item, stocks),
                                user_input, {"nome": item[F_NAME]})

    async def async_step_modifica_singola(self, user_input=None) -> ConfigFlowResult:
        item = self._manager.get(self._edit_id)
        return await self._save(KIND_ONCE, "modifica_singola", _once_schema(user_input or item),
                                user_input, {"nome": item[F_NAME]})

    async def async_step_modifica_scorta(self, user_input=None) -> ConfigFlowResult:
        item = self._manager.get(self._edit_id)
        defaults = user_input or {**item, F_QUANTITY: round(stock_level(item), 1)}
        return await self._save(KIND_STOCK, "modifica_scorta", _stock_schema(defaults, False),
                                user_input, {"nome": item[F_NAME]})

    async def async_step_elimina(self, user_input=None) -> ConfigFlowResult:
        if not self._manager.items:
            return self.async_abort(reason="nessun_articolo")
        if user_input is not None:
            for item_id in user_input.get(ITEMS_SELECT, []):
                await self._manager.async_remove(item_id)
            return self._done()
        return self.async_show_form(
            step_id="elimina",
            data_schema=vol.Schema(
                {
                    vol.Required(ITEMS_SELECT, default=[]): sel.SelectSelector(
                        sel.SelectSelectorConfig(
                            options=[sel.SelectOptionDict(value=v, label=l) for v, l in self._item_options()],
                            multiple=True, mode=sel.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
