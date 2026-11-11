"""Costanti per Scorte e Scadenze."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "scorte_scadenze"
VERSION = "2.0.0"
TITLE = "Scorte e Scadenze"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.TODO,
]

# Tipi di articolo
KIND_TASK = "scadenza"  # promemoria ricorrente (nome storico mantenuto per compatibilità)
KIND_ONCE = "singola"  # scadenza singola
KIND_STOCK = "scorta"  # prodotto
KINDS = (KIND_TASK, KIND_ONCE, KIND_STOCK)
REMINDER_KINDS = (KIND_TASK, KIND_ONCE)

# Modalità scorta
MODE_PIECES = "pezzi"
MODE_RATE = "consumo"

# Unità intervallo
UNIT_DAYS = "giorni"
UNIT_WEEKS = "settimane"
UNIT_MONTHS = "mesi"

# Opzioni generali
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_NOTIFY_TIME = "notify_time"
CONF_SHOPPING_ENABLED = "shopping_enabled"
CONF_SHOPPING_LIST = "shopping_list"

DEFAULT_NOTIFY_TIME = "09:00:00"
DEFAULT_SHOPPING_LIST = "todo.shopping_list"
QUIET_FROM = "22:00:00"  # dopo quest'ora niente avvisi urgenti

# Campi articolo
F_ID = "id"
F_NAME = "name"
F_KIND = "kind"
F_ICON = "icon"
F_INTERVAL = "interval"
F_INTERVAL_UNIT = "interval_unit"
F_LAST_DONE = "last_done"
F_DUE_DATE = "data_scadenza"
F_ADVANCE = "preavviso"
F_LINKED_STOCK = "linked_stock"
F_LINKED_QTY = "linked_qty"
F_MODE = "mode"
F_UNIT = "unit"
F_QUANTITY = "quantity"
F_REF_DATE = "ref_date"
F_DAILY_RATE = "daily_rate"
F_THRESHOLD = "threshold"
F_REORDER = "riordino"
F_AFTER_OPEN = "dopo_apertura"
F_EXP_ADVANCE = "preavviso_scadenza"
F_INITIAL_EXPIRY = "scadenza"
F_LOTS = "lotti"
F_HISTORY = "storico"
F_IN_LIST = "in_lista"

# Campi confezione (lotto)
L_ID = "id"
L_QTY = "qty"
L_BOUGHT = "acquisto"
L_EXPIRY = "scadenza"
L_OPENED = "aperta"

NO_LINK = "nessuna"
HISTORY_MAX = 30
CHECK_INTERVAL_MINUTES = 15

SIGNAL_UPDATE = f"{DOMAIN}_update"
SIGNAL_NEW_ITEM = f"{DOMAIN}_new_item"
EVENT_ALERT = f"{DOMAIN}_avviso"
EVENT_DIGEST = f"{DOMAIN}_riepilogo"

SUMMARY_ENTITY_ID = "sensor.scorte_scadenze_riepilogo"
CARD_FILENAME = "scorte-scadenze-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"

DEFAULT_TASK_ICON = "mdi:calendar-sync"
DEFAULT_ONCE_ICON = "mdi:calendar-alert"
DEFAULT_STOCK_ICON = "mdi:package-variant-closed"
