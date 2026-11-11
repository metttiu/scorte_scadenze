# Scorte e Scadenze

Integrazione per Home Assistant che gestisce tre cose:
- **promemoria ricorrenti**, come il cambio dei filtri dell'acquario ogni mese;
- **scadenze singole**, come bollo, assicurazione o garanzia;
- **prodotti in casa**, con giacenza, soglia di riordino, scadenza di ogni confezione e "da consumare entro N giorni dall'apertura".

Tutto si gestisce dalla card in dashboard: aggiungere, modificare, segnare come fatto, registrare acquisti, aprire e togliere confezioni.

## Installazione

**HACS**: HACS › Integrazioni › ⋮ › Repository personalizzati › aggiungi l'URL del repository (categoria *Integrazione*), installa e riavvia.

**Manuale**: copia `custom_components/scorte_scadenze` in `/config/custom_components/` e riavvia.

Poi: Impostazioni › Dispositivi e servizi › Aggiungi integrazione › *Scorte e Scadenze*. La card si carica da sola.

```yaml
type: custom:scorte-scadenze-card
titolo: Casa        # facoltativo
conferma: true      # "Fatto" chiede un secondo tocco di conferma
```

## Uso della card

- **+** in alto: scegli Promemoria, Scadenza o Prodotto. Compili solo i campi essenziali; il resto è in "Altre opzioni".
- **Filtri**: Tutto, Da fare, Spesa, Scadenze, ciascuno con il numero di voci da gestire.
- **Tutto** mostra in alto la sezione *Adesso*, con solo ciò che richiede un'azione. Sotto ci sono *Promemoria* e *Prodotti*, richiudibili; la scelta viene ricordata.
- **Tocco su una voce**: apre la scheda con dettagli, confezioni, ultimi acquisti, *Modifica* ed *Elimina*.
- **Sui prodotti**: `−1` scala un pezzo, `+` registra un acquisto con quantità, data ed eventuale scadenza.
- **Sulle confezioni**: *Apri* la segna aperta da oggi e attiva il conteggio "da consumare entro". *Finita* o *Buttata* la toglie dalla giacenza.

I consumi escono prima dalle confezioni aperte, poi da quelle che scadono prima.

## Notifiche

- **Riepilogo giornaliero**: un solo messaggio all'ora scelta, con tutto ciò che va gestito, diviso in Da fare, Scadenze prodotti e Da comprare.
- **Urgenti subito**: promemoria del giorno o scaduti, confezioni da consumare oggi o scadute, prodotti esauriti. Arrivano solo tra l'ora del riepilogo e le 22.
- **Destinatari**: servizi (`notify.mobile_app_telefono`, `notify.telegram`) o entità notify.

I prodotti sotto soglia vanno nella lista della spesa scelta e ne escono quando registri l'acquisto.

Eventi per automazioni personalizzate, ad esempio pulsanti inline su Telegram:
- `scorte_scadenze_riepilogo` con `messaggio` e `avvisi`;
- `scorte_scadenze_avviso` con `item_id`, `nome`, `tipo`, `messaggio`, `confezione`.

## Servizi

Ogni servizio accetta `entity_id` (qualsiasi entità dell'articolo) oppure `item_id`.

| Servizio | Campi |
|---|---|
| `scorte_scadenze.fatto` | `data` facoltativa. Una scadenza singola fatta viene eliminata |
| `scorte_scadenze.acquisto` | `quantita`, `data` e `scadenza` facoltative |
| `scorte_scadenze.consumo` | `quantita` |
| `scorte_scadenze.imposta_giacenza` | `quantita` |
| `scorte_scadenze.apri` | `confezione` facoltativa (predefinita: quella che scade prima) |
| `scorte_scadenze.togli_confezione` | `confezione` |

Esempio: un pulsante ESPHome vicino alla macchina del caffè.

```yaml
action: scorte_scadenze.consumo
data:
  entity_id: sensor.cialde_caffe_giacenza
  quantita: 1
```

## Entità

| Tipo | Entità |
|---|---|
| Promemoria e scadenze | `Scadenza`, `Giorni rimanenti`, `Da fare`, pulsante `Segna come fatto` |
| Prodotti | `Giacenza`, `Prima scadenza`, `Autonomia` (solo a consumo), `Da acquistare`, `In scadenza`, pulsante `Registra riordino` |
| Globali | `todo.scorte_e_scadenze` (spuntare una voce esegue l'azione) e `sensor.scorte_scadenze_riepilogo` |

## Dati

Sono salvati in `/config/.storage/scorte_scadenze` e quindi inclusi nei backup. La versione 1.x viene migrata in automatico: la giacenza esistente diventa una confezione senza scadenza.
