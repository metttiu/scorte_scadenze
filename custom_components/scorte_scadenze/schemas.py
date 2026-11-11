"""Validazione e normalizzazione dei dati articolo (condivisa da card e menu Configura)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import (
    DEFAULT_ONCE_ICON,
    DEFAULT_STOCK_ICON,
    DEFAULT_TASK_ICON,
    F_ADVANCE,
    F_AFTER_OPEN,
    F_DAILY_RATE,
    F_DUE_DATE,
    F_EXP_ADVANCE,
    F_ICON,
    F_INITIAL_EXPIRY,
    F_INTERVAL,
    F_INTERVAL_UNIT,
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
    UNIT_DAYS,
    UNIT_MONTHS,
    UNIT_WEEKS,
)


def iso_date(value: Any) -> str:
    """Accetta date/datetime/stringa e restituisce YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return cv.date(str(value).strip()).isoformat()


def optional_iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return iso_date(value)


_NAME = vol.All(cv.string, vol.Strip, vol.Length(min=1, msg="nome_vuoto"))
_POS_INT = vol.All(vol.Coerce(int), vol.Range(min=0, max=3650))
_POS_FLOAT = vol.All(vol.Coerce(float), vol.Range(min=0, max=1_000_000))
_ICON = vol.Any(None, "", cv.icon)

TASK_SCHEMA = vol.Schema(
    {
        vol.Required(F_NAME): _NAME,
        vol.Required(F_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=1, max=3650)),
        vol.Required(F_INTERVAL_UNIT): vol.In([UNIT_DAYS, UNIT_WEEKS, UNIT_MONTHS]),
        vol.Required(F_LAST_DONE): iso_date,
        vol.Optional(F_ADVANCE, default=0): _POS_INT,
        vol.Optional(F_LINKED_STOCK, default=NO_LINK): vol.Any(None, cv.string),
        vol.Optional(F_LINKED_QTY, default=1): _POS_FLOAT,
        vol.Optional(F_ICON, default=DEFAULT_TASK_ICON): _ICON,
    },
    extra=vol.REMOVE_EXTRA,
)

ONCE_SCHEMA = vol.Schema(
    {
        vol.Required(F_NAME): _NAME,
        vol.Required(F_DUE_DATE): iso_date,
        vol.Optional(F_ADVANCE, default=0): _POS_INT,
        vol.Optional(F_ICON, default=DEFAULT_ONCE_ICON): _ICON,
    },
    extra=vol.REMOVE_EXTRA,
)

STOCK_SCHEMA = vol.Schema(
    {
        vol.Required(F_NAME): _NAME,
        vol.Optional(F_MODE, default=MODE_PIECES): vol.In([MODE_PIECES, MODE_RATE]),
        vol.Optional(F_UNIT, default=""): vol.Any(None, vol.All(cv.string, vol.Strip)),
        vol.Optional(F_QUANTITY): _POS_FLOAT,
        vol.Optional(F_DAILY_RATE, default=0): _POS_FLOAT,
        vol.Optional(F_THRESHOLD, default=1): _POS_FLOAT,
        vol.Optional(F_REORDER, default=1): _POS_FLOAT,
        vol.Optional(F_AFTER_OPEN, default=0): _POS_INT,
        vol.Optional(F_EXP_ADVANCE, default=2): _POS_INT,
        vol.Optional(F_INITIAL_EXPIRY): optional_iso_date,
        vol.Optional(F_ICON, default=DEFAULT_STOCK_ICON): _ICON,
    },
    extra=vol.REMOVE_EXTRA,
)

SCHEMAS = {KIND_TASK: TASK_SCHEMA, KIND_ONCE: ONCE_SCHEMA, KIND_STOCK: STOCK_SCHEMA}
DEFAULT_ICONS = {KIND_TASK: DEFAULT_TASK_ICON, KIND_ONCE: DEFAULT_ONCE_ICON, KIND_STOCK: DEFAULT_STOCK_ICON}


class ItemValidationError(ValueError):
    """Errore di validazione con campo e codice traducibile."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


_MESSAGES = {
    "nome_vuoto": "Inserisci un nome.",
    "consumo_richiesto": "Con il calcolo a consumo serve un consumo giornaliero maggiore di zero.",
}


def validate_item(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Valida i dati di un articolo; solleva ItemValidationError."""
    if kind not in SCHEMAS:
        raise ItemValidationError("base", "tipo_non_valido", f"Tipo non valido: {kind}")
    clean_input = {k: v for k, v in data.items() if v is not None}
    try:
        out = SCHEMAS[kind](clean_input)
    except vol.MultipleInvalid as err:
        first = err.errors[0]
        field = str(first.path[0]) if first.path else "base"
        code = first.error_message if first.error_message in _MESSAGES else "valore_non_valido"
        raise ItemValidationError(
            field, code, _MESSAGES.get(code, f"Valore non valido per {field}")
        ) from err
    if not out.get(F_ICON):
        out[F_ICON] = DEFAULT_ICONS[kind]
    if kind == KIND_TASK and not out.get(F_LINKED_STOCK):
        out[F_LINKED_STOCK] = NO_LINK
    if kind == KIND_STOCK:
        out[F_UNIT] = out.get(F_UNIT) or ""
        if out[F_MODE] == MODE_RATE and out[F_DAILY_RATE] <= 0:
            raise ItemValidationError(F_DAILY_RATE, "consumo_richiesto", _MESSAGES["consumo_richiesto"])
    return out
