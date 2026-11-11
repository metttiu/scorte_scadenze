from datetime import date, timedelta

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.scorte_scadenze.const import DOMAIN, EVENT_DIGEST


async def _setup(hass: HomeAssistant, notify_time="09:00:00"):
    await hass.config.async_set_time_zone("Europe/Rome")
    await async_setup_component(hass, "websocket_api", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"notify_targets": ["notify.telefono", " "], "notify_time": notify_time,
         "shopping_enabled": True, "shopping_list": "todo.spesa"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


def _mock_shopping(hass):
    hass.states.async_set("todo.spesa", "0")
    async_mock_service(hass, "todo", "get_items", response={"todo.spesa": {"items": []}},
                       supports_response=SupportsResponse.ONLY)
    return async_mock_service(hass, "todo", "add_item"), async_mock_service(hass, "todo", "remove_item")


async def _ws(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_card_crud_confezioni_e_notifiche(hass, hass_ws_client, freezer):
    notifiche = async_mock_service(hass, "notify", "telefono")
    entry = await _setup(hass)
    add, remove = _mock_shopping(hass)  # dopo il setup: sostituisce i servizi todo reali
    m = entry.runtime_data
    client = await hass_ws_client(hass)  # autenticazione con l'orario reale
    freezer.move_to("2026-11-08 07:00:00+01:00")  # prima dell'ora del riepilogo
    reg = er.async_get(hass)

    # Errore di validazione dalla card
    r = await _ws(client, type=f"{DOMAIN}/salva", tipo="scorta",
                  dati={"name": "Cialde", "mode": "consumo", "daily_rate": 0})
    assert not r["success"] and r["error"]["code"] == "consumo_richiesto"

    # Marmellata: 2 vasetti con scadenza, consumare entro 10 giorni dall'apertura
    r = await _ws(client, type=f"{DOMAIN}/salva", tipo="scorta", dati={
        "name": "Marmellata", "mode": "pezzi", "unit": "vasetti", "quantity": 2, "threshold": 0,
        "riordino": 2, "dopo_apertura": 10, "preavviso_scadenza": 2, "scadenza": "2027-03-01"})
    assert r["success"]
    marm = r["result"]["item_id"]
    await hass.async_block_till_done()
    # Entità create subito, senza ricaricare
    ent_scad = reg.async_get_entity_id("binary_sensor", DOMAIN, f"{marm}_in_scadenza")
    assert hass.states.get(ent_scad).state == "off"

    # Scadenza singola e promemoria ricorrente
    r = await _ws(client, type=f"{DOMAIN}/salva", tipo="singola",
                  dati={"name": "Bollo auto", "data_scadenza": "2026-11-08", "preavviso": 3})
    bollo = r["result"]["item_id"]
    r = await _ws(client, type=f"{DOMAIN}/salva", tipo="scadenza",
                  dati={"name": "Filtro acquario", "interval": 30, "interval_unit": "giorni",
                        "last_done": "2026-10-20"})
    filtro = r["result"]["item_id"]
    await hass.async_block_till_done()
    assert notifiche == []  # prima delle 9 niente
    await client.close()

    # Apro un vasetto: si separa dalla confezione da 2
    await hass.services.async_call(DOMAIN, "apri", {"item_id": marm}, blocking=True)
    lotti = m.items[marm]["lotti"]
    assert sorted(l["qty"] for l in lotti) == [1, 1]
    assert any(l["aperta"] == "2026-11-08" for l in lotti)

    # 9 giorni dopo, alle 9:30: riepilogo unico con bollo scaduto, marmellata in scadenza
    freezer.move_to("2026-11-17 09:30:00+01:00")
    digest = []
    hass.bus.async_listen(EVENT_DIGEST, lambda e: digest.append(e))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(notifiche) == 1, [c.data for c in notifiche]
    msg = notifiche[0].data["message"]
    assert "Bollo auto" in msg and "Marmellata (aperta)" in msg and "Filtro acquario" not in msg
    assert len(digest) == 1
    assert hass.states.get(ent_scad).state == "on"

    # Stesso giorno: il filtro diventa da fare il 19; nessun nuovo messaggio oggi
    async_fire_time_changed(hass, dt_util.now() + timedelta(minutes=20))
    await hass.async_block_till_done()
    assert len(notifiche) == 1

    # Urgente immediato: finisce la marmellata chiusa (consumo 1) e quella aperta viene tolta -> esaurita
    aperta = next(l["id"] for l in m.items[marm]["lotti"] if l["aperta"])
    await hass.services.async_call(DOMAIN, "consumo", {"item_id": marm, "quantita": 1}, blocking=True)
    # consumo usa prima la confezione aperta
    assert [l["aperta"] for l in m.items[marm]["lotti"]] == [None]
    await hass.services.async_call(DOMAIN, "consumo", {"item_id": marm, "quantita": 1}, blocking=True)
    await hass.async_block_till_done()
    assert any("Marmellata: esaurito" in c.data["message"] for c in notifiche), [(c.data, m.meta, [a.key for a in m.alerts()]) for c in notifiche]
    assert any(c.data["item"] == "Marmellata" for c in add)

    # Acquisto con scadenza -> esce dalla lista spesa
    hass.states.async_set("todo.spesa", "1")
    async_mock_service(hass, "todo", "get_items", response={"todo.spesa": {"items": [{"summary": "Marmellata"}]}},
                       supports_response=SupportsResponse.ONLY)
    await hass.services.async_call(DOMAIN, "acquisto",
        {"item_id": marm, "quantita": 3, "scadenza": "2027-05-01"}, blocking=True)
    await hass.async_block_till_done()
    assert len(remove) == 1
    assert m.items[marm]["lotti"][0]["scadenza"] == "2027-05-01"

    # Todo nativa: bollo -> fatto = eliminato
    todo_id = reg.async_get_entity_id("todo", DOMAIN, f"{entry.entry_id}_da_fare")
    await hass.services.async_call("todo", "update_item",
        {"entity_id": todo_id, "item": "Bollo auto", "status": "completed"}, blocking=True)
    await hass.async_block_till_done()
    assert bollo not in m.items

    await entry.runtime_data.async_remove(filtro)

    riep = hass.states.get("sensor.scorte_scadenze_riepilogo")
    assert [a["nome"] for a in riep.attributes["articoli"]] == ["Marmellata"]

    # Persistenza
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.items) == 1


async def test_card_modifica_elimina(hass, hass_ws_client):
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    r = await _ws(client, type=f"{DOMAIN}/salva", tipo="scadenza",
                  dati={"name": "Filtro", "interval": 30, "interval_unit": "giorni", "last_done": "2026-10-20"})
    filtro = r["result"]["item_id"]
    r = await _ws(client, type=f"{DOMAIN}/salva", item_id=filtro, tipo="singola", dati={"name": "x", "data_scadenza": "2027-01-01"})
    assert not r["success"]  # il tipo non si cambia
    r = await _ws(client, type=f"{DOMAIN}/salva", item_id=filtro, tipo="scadenza",
                  dati={"name": "Cambio filtro", "interval": 1, "interval_unit": "mesi", "last_done": "2026-10-20"})
    assert r["success"]
    from homeassistant.helpers import device_registry as dr
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, filtro)}).name == "Cambio filtro"
    r = await _ws(client, type=f"{DOMAIN}/elimina", item_id=filtro)
    assert r["success"] and filtro not in entry.runtime_data.items
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, filtro)}) is None


async def test_cialde_a_consumo(hass, freezer):
    freezer.move_to("2026-11-08 10:00:00+01:00")
    async_mock_service(hass, "notify", "telefono")
    entry = await _setup(hass, notify_time="00:00:00")
    _mock_shopping(hass)
    m = entry.runtime_data
    cialde = await m.async_create("scorta", {"name": "Cialde", "mode": "consumo", "unit": "cialde",
        "quantity": 100, "daily_rate": 3, "threshold": 20, "riordino": 150, "dopo_apertura": 0,
        "preavviso_scadenza": 2, "icon": "mdi:coffee"})
    freezer.tick(timedelta(days=10))
    assert round(m.summary()[0]["giacenza"]) == 70
    # acquisto 150 cialde 2 giorni fa: livello già >0, si aggiungono tutte
    await m.async_purchase(cialde, 150, dt_util.now() - timedelta(days=2))
    assert round(m.summary()[0]["giacenza"]) == 220
    # le confezioni seguono il consumo
    freezer.tick(timedelta(days=30))
    view = m.summary()[0]["confezioni"]
    assert round(sum(l["qta"] for l in view)) == 130
    # cambio modalità -> ricarica, compare/scompare il sensore Autonomia
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{cialde}_autonomia")


async def test_migrazione_v1(hass, hass_storage, freezer):
    await hass.config.async_set_time_zone("Europe/Rome")
    freezer.move_to("2026-11-08 10:00:00+01:00")
    hass_storage[DOMAIN] = {"version": 1, "minor_version": 1, "key": DOMAIN, "data": {"items": {
        "abc": {"id": "abc", "kind": "scorta", "name": "Filtri", "mode": "pezzi", "unit": "pz",
                "quantity": 3, "ref_date": "2026-11-01T10:00:00+01:00", "daily_rate": 0, "threshold": 1,
                "riordino": 4, "icon": "mdi:filter", "notified": False, "storico": [], "in_lista": False}}}}
    entry = MockConfigEntry(domain=DOMAIN, options={"notify_targets": [], "notify_time": "09:00:00",
                                                    "shopping_enabled": False})
    entry.add_to_hass(hass)
    await async_setup_component(hass, "websocket_api", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    item = entry.runtime_data.items["abc"]
    assert item["lotti"][0]["qty"] == 3 and "notified" not in item


async def test_menu_configura(hass, freezer):
    freezer.move_to("2026-11-08 10:00:00+01:00")
    entry = await _setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "aggiungi_scorta"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "name": "X", "mode": "consumo", "unit": "pz", "quantity": 5, "daily_rate": 0, "threshold": 1,
        "riordino": 1, "dopo_apertura": 0, "preavviso_scadenza": 2, "icon": "mdi:x"})
    assert r["errors"] == {"daily_rate": "consumo_richiesto"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "name": "Latte", "mode": "pezzi", "unit": "brick", "quantity": 4, "daily_rate": 0, "threshold": 1,
        "riordino": 6, "dopo_apertura": 4, "preavviso_scadenza": 1, "scadenza": "2026-12-01", "icon": "mdi:cup"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    item = next(iter(entry.runtime_data.items.values()))
    assert item["lotti"][0]["scadenza"] == "2026-12-01"
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "modifica"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"articolo": item["id"]})
    assert r["step_id"] == "modifica_scorta"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "name": "Latte", "mode": "pezzi", "unit": "brick", "quantity": 2, "daily_rate": 0, "threshold": 1,
        "riordino": 6, "dopo_apertura": 4, "preavviso_scadenza": 1, "icon": "mdi:cup"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.items[item["id"]]["quantity"] == 2


async def test_mesi_fine_mese():
    from custom_components.scorte_scadenze.manager import add_months
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
