/* Scorte e Scadenze – card Lovelace v2 */
const CARD_VERSION = "2.0.0";
const DOMAIN = "scorte_scadenze";
const DEFAULT_ENTITY = "sensor.scorte_scadenze_riepilogo";
const K_TASK = "scadenza";
const K_ONCE = "singola";
const K_STOCK = "scorta";

const ICONS = {
  [K_TASK]: ["mdi:calendar-sync", "mdi:fishbowl", "mdi:air-filter", "mdi:car-wrench", "mdi:water-boiler", "mdi:flower", "mdi:broom", "mdi:dog"],
  [K_ONCE]: ["mdi:calendar-alert", "mdi:car", "mdi:file-document", "mdi:shield-check", "mdi:credit-card", "mdi:school", "mdi:passport", "mdi:gift"],
  [K_STOCK]: ["mdi:package-variant-closed", "mdi:coffee", "mdi:filter", "mdi:jar", "mdi:bottle-wine", "mdi:food-apple", "mdi:spray-bottle", "mdi:paper-roll"],
};

// ---------------------------------------------------------------- utilità

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmt = (n) => {
  const r = Math.round(Number(n) * 10) / 10;
  return Number.isInteger(r) ? String(r) : String(r).replace(".", ",");
};

const num = (v) => {
  const n = parseFloat(String(v ?? "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
};

const isoToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const dayLabel = (iso, year = false) =>
  iso
    ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("it-IT", {
        day: "numeric",
        month: "short",
        ...(year ? { year: "numeric" } : {}),
      })
    : "";

const whenText = (days) => {
  if (days > 1) return `tra ${days} giorni`;
  if (days === 1) return "domani";
  if (days === 0) return "oggi";
  if (days === -1) return "da ieri";
  return `da ${-days} giorni`;
};

const dueText = (days) => {
  if (days < -1) return `scaduto da ${-days} giorni`;
  if (days === -1) return "scaduto ieri";
  return whenText(days);
};

const unitText = (u) => (u ? ` ${esc(u)}` : "");

const reminderSub = (i) => {
  if (i.giorni < 0) return `Scaduto ${whenText(i.giorni)}`;
  if (i.giorni === 0) return "Da fare oggi";
  return `${i.da_fare ? "Da fare" : "Prossima"} ${whenText(i.giorni)}, ${dayLabel(i.prossima)}`;
};

const lotSub = (lot, item) => {
  const parts = [];
  if (lot.aperta) parts.push(`aperta il ${dayLabel(lot.aperta)}`);
  if (lot.entro) {
    if (lot.giorni < 0) parts.push(`scaduta il ${dayLabel(lot.entro)}`);
    else if (lot.giorni === 0) parts.push("da consumare oggi");
    else parts.push(`entro ${dayLabel(lot.entro, lot.giorni > 300)} (${whenText(lot.giorni)})`);
  } else if (!lot.aperta) parts.push("senza scadenza");
  const qty = lot.qta !== 1 ? `${fmt(lot.qta)}${item.unita ? " " + item.unita : ""}, ` : "";
  const text = qty + parts.join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

const lotAction = (lot, item) => {
  if (lot.giorni !== null && lot.giorni < 0) return { act: "lot-remove", label: "Buttata" };
  if (!lot.aperta && item.dopo_apertura > 0) return { act: "lot-open", label: "Apri" };
  return { act: "lot-remove", label: "Finita" };
};

// ---------------------------------------------------------------- card

class ScorteScadenzeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._filter = "tutto";
    this._busy = new Set();
    this._confirm = null;
    this._sig = "";
    this._dialog = null;
  }

  setConfig(config) {
    this._config = {
      entity: DEFAULT_ENTITY,
      titolo: "Scorte e Scadenze",
      conferma: true,
      ...config,
    };
    try {
      this._collapsed = JSON.parse(localStorage.getItem(`scorte-scadenze:${this._config.entity}`)) || {};
    } catch (_e) {
      this._collapsed = {};
    }
    this._sig = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const sig = st ? JSON.stringify([st.attributes.articoli, st.attributes.avvisi]) : "missing";
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
    this._dialog?.refresh();
  }

  disconnectedCallback() {
    this._dialog?.close();
  }

  getCardSize() {
    return 3 + Math.min(this._alerts().length, 6);
  }

  static getStubConfig() {
    return { entity: DEFAULT_ENTITY };
  }

  // ---- dati

  _state() {
    return this._hass?.states[this._config.entity];
  }

  _items() {
    return this._state()?.attributes?.articoli ?? [];
  }

  _alerts() {
    return this._state()?.attributes?.avvisi ?? [];
  }

  item(id) {
    return this._items().find((i) => i.id === id);
  }

  products() {
    return this._items().filter((i) => i.tipo === K_STOCK);
  }

  // ---- azioni

  async call(service, data, busyKey) {
    this._busy.add(busyKey);
    this._render();
    this._dialog?.refresh();
    try {
      await this._hass.callService(DOMAIN, service, data);
      return true;
    } catch (err) {
      this.toast(`Operazione non riuscita: ${err.message ?? err}`);
      return false;
    } finally {
      this._busy.delete(busyKey);
      this._sig = "";
      this._render();
      this._dialog?.refresh();
    }
  }

  ws(msg) {
    return this._hass.callWS({ type: `${DOMAIN}/${msg.type}`, ...msg.data });
  }

  toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  busy(key) {
    return this._busy.has(key);
  }

  openDialog(view, id) {
    if (!this._dialog) this._dialog = new SsDialog(this);
    this._dialog.show(view, id);
  }

  // ---- rendering righe

  _reminderRow(i, compact = false) {
    const state = i.giorni < 0 ? "late" : i.da_fare ? "due" : "ok";
    const confirming = this._confirm === i.id;
    const busy = this.busy(i.id);
    return `
      <div class="row ${state}">
        <button class="main" data-act="detail" data-id="${i.id}" aria-label="Dettagli ${esc(i.nome)}">
          <span class="badge"><ha-icon icon="${esc(i.icona || "mdi:calendar-check")}"></ha-icon></span>
          <span class="text">
            <span class="name">${esc(i.nome)}</span>
            <span class="sub">${esc(reminderSub(i))}${!compact && i.tipo === K_ONCE ? ", una tantum" : ""}</span>
          </span>
        </button>
        <div class="actions">
          <button class="btn ${i.da_fare ? "primary" : ""} ${confirming ? "confirm" : ""}"
                  data-act="done" data-id="${i.id}" ${busy ? "disabled" : ""}>
            ${busy ? "…" : confirming ? "Confermi?" : "Fatto"}
          </button>
        </div>
      </div>`;
  }

  _productRow(i) {
    const scale = Math.max(i.soglia * 3, i.soglia + i.riordino, i.giacenza, 1);
    const fill = Math.min(100, (i.giacenza / scale) * 100);
    const tick = Math.min(100, (i.soglia / scale) * 100);
    const parts = [];
    if (i.giacenza <= 0) parts.push("Esaurito");
    else if (i.autonomia !== null && i.autonomia !== undefined) parts.push(`Circa ${fmt(i.autonomia)} giorni`);
    if (i.sotto_soglia && i.giacenza > 0) parts.push("da comprare");
    const exp = (i.confezioni || []).filter((l) => l.entro).sort((a, b) => a.giorni - b.giorni)[0];
    if (exp) parts.push(`prima scadenza ${dayLabel(exp.entro)}`);
    const sub = parts.join(", ") || `Soglia ${fmt(i.soglia)}${i.unita ? " " + i.unita : ""}`;
    const busy = this.busy(i.id);
    return `
      <div class="row ${i.sotto_soglia ? "low" : "ok"}">
        <button class="main" data-act="detail" data-id="${i.id}" aria-label="Dettagli ${esc(i.nome)}">
          <span class="badge"><ha-icon icon="${esc(i.icona || "mdi:package-variant-closed")}"></ha-icon></span>
          <span class="text">
            <span class="name">${esc(i.nome)}</span>
            <span class="gauge" aria-hidden="true"><span class="fill" style="width:${fill}%"></span><span class="tick" style="left:${tick}%"></span></span>
            <span class="sub">${esc(sub.charAt(0).toUpperCase() + sub.slice(1))}</span>
          </span>
          <span class="qty">${fmt(i.giacenza)}<small>${unitText(i.unita)}</small></span>
        </button>
        <div class="actions">
          ${i.modalita === "pezzi"
            ? `<button class="btn icon" aria-label="Consuma 1 ${esc(i.nome)}" data-act="use" data-id="${i.id}"
                 ${busy || i.giacenza <= 0 ? "disabled" : ""}>−1</button>`
            : ""}
          <button class="btn icon ${i.sotto_soglia ? "primary" : ""}" aria-label="Aggiungi ${esc(i.nome)}"
                  data-act="buy" data-id="${i.id}" ${busy ? "disabled" : ""}>+</button>
        </div>
      </div>`;
  }

  _lotRow(item, lot) {
    const state = lot.giorni !== null && lot.giorni < 0 ? "late" : lot.avviso ? "due" : "ok";
    const action = lotAction(lot, item);
    const key = `${item.id}:${lot.id}`;
    const busy = this.busy(key);
    return `
      <div class="row ${state}">
        <button class="main" data-act="detail" data-id="${item.id}" aria-label="Dettagli ${esc(item.nome)}">
          <span class="badge"><ha-icon icon="${esc(lot.aperta ? "mdi:jar-outline" : item.icona || "mdi:timer-sand")}"></ha-icon></span>
          <span class="text">
            <span class="name">${esc(item.nome)}${lot.aperta ? " (aperta)" : ""}</span>
            <span class="sub">${esc(lotSub(lot, item))}</span>
          </span>
        </button>
        <div class="actions">
          <button class="btn ${lot.avviso ? "primary" : ""}" data-act="${action.act}" data-id="${item.id}"
                  data-lot="${lot.id}" ${busy ? "disabled" : ""}>${busy ? "…" : action.label}</button>
        </div>
      </div>`;
  }

  _section(key, title, rows, collapsible) {
    if (!rows.length) return "";
    const closed = collapsible && this._collapsed[key];
    const head = collapsible
      ? `<button class="sec-head" data-act="toggle" data-id="${key}" aria-expanded="${!closed}">
           <span>${title}</span><span class="sec-count">${rows.length}</span>
           <ha-icon icon="${closed ? "mdi:chevron-down" : "mdi:chevron-up"}"></ha-icon>
         </button>`
      : `<h3>${title}</h3>`;
    return `<section>${head}${closed ? "" : rows.join("")}</section>`;
  }

  _content() {
    const items = this._items();
    const alerts = this._alerts();
    const reminders = items.filter((i) => i.tipo !== K_STOCK).sort((a, b) => a.giorni - b.giorni);
    const products = items.filter((i) => i.tipo === K_STOCK);
    const lots = products
      .flatMap((p) => (p.confezioni || []).filter((l) => l.entro).map((l) => [p, l]))
      .sort((a, b) => a[1].giorni - b[1].giorni);

    if (this._filter === "fare") {
      return reminders.length
        ? this._section("f", "Promemoria", reminders.map((i) => this._reminderRow(i)), false)
        : `<p class="empty">Nessun promemoria. Aggiungine uno con +.</p>`;
    }
    if (this._filter === "spesa") {
      const low = products.filter((p) => p.sotto_soglia);
      return low.length
        ? this._section("s", "Da comprare", low.map((p) => this._productRow(p)), false)
        : `<p class="empty">Niente da comprare.</p>`;
    }
    if (this._filter === "scadenze") {
      return lots.length
        ? this._section("x", "Confezioni per scadenza", lots.map(([p, l]) => this._lotRow(p, l)), false)
        : `<p class="empty">Nessuna confezione con scadenza. La data si inserisce quando registri un acquisto.</p>`;
    }

    // Tutto: prima ciò che serve adesso, poi le sezioni per tipo (chiudibili)
    const order = { fare: 0, scadenze: 1, spesa: 2 };
    const now = [...alerts]
      .sort((a, b) => b.urgente - a.urgente || order[a.gruppo] - order[b.gruppo])
      .map((a) => {
        const it = this.item(a.item_id);
        if (!it) return "";
        if (a.gruppo === "fare") return this._reminderRow(it, true);
        if (a.gruppo === "spesa") return this._productRow(it);
        const lot = (it.confezioni || []).find((l) => l.id === a.confezione);
        return lot ? this._lotRow(it, lot) : "";
      })
      .filter(Boolean);
    const alerted = new Set(alerts.filter((a) => a.gruppo !== "scadenze").map((a) => a.item_id));
    const restReminders = reminders.filter((i) => !alerted.has(i.id));
    const restProducts = products
      .filter((i) => !alerted.has(i.id))
      .sort((a, b) => a.nome.localeCompare(b.nome, "it"));

    if (!items.length) {
      return `<p class="empty">Ancora niente qui. Usa + per aggiungere un promemoria (es. cambio filtro), una scadenza (es. bollo auto) o un prodotto (es. cialde).</p>`;
    }
    return `
      ${now.length ? this._section("adesso", "Adesso", now, false) : `<p class="calm">Niente da gestire adesso.</p>`}
      ${this._section("promemoria", "Promemoria", restReminders.map((i) => this._reminderRow(i)), true)}
      ${this._section("prodotti", "Prodotti", restProducts.map((i) => this._productRow(i)), true)}`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const st = this._state();
    const alerts = this._alerts();
    const count = (g) => alerts.filter((a) => a.gruppo === g).length;
    const pills = [
      ["tutto", "Tutto", 0],
      ["fare", "Da fare", count("fare")],
      ["spesa", "Spesa", count("spesa")],
      ["scadenze", "Scadenze", count("scadenze")],
    ];
    const body = st
      ? `<nav class="pills" aria-label="Filtro">
           ${pills
             .map(
               ([k, label, n]) =>
                 `<button class="pill ${this._filter === k ? "on" : ""}" data-act="filter" data-id="${k}"
                          aria-pressed="${this._filter === k}">${label}${n ? `<span class="n">${n}</span>` : ""}</button>`
             )
             .join("")}
         </nav>
         ${this._content()}`
      : `<p class="empty">Entità ${esc(this._config.entity)} non trovata. Controlla che l'integrazione Scorte e Scadenze sia configurata.</p>`;

    this.shadowRoot.innerHTML = `
      <style>${CARD_STYLE}</style>
      <ha-card>
        <header>
          <h2>${esc(this._config.titolo)}</h2>
          ${st ? `<button class="add" data-act="add" aria-label="Aggiungi"><ha-icon icon="mdi:plus"></ha-icon></button>` : ""}
        </header>
        ${body}
      </ha-card>`;
    this.shadowRoot.querySelectorAll("[data-act]").forEach((b) =>
      b.addEventListener("click", (e) => this._onAction(e.currentTarget))
    );
  }

  _onAction(el) {
    const { act, id, lot } = el.dataset;
    switch (act) {
      case "filter":
        this._filter = id;
        this._render();
        break;
      case "toggle":
        this._collapsed[id] = !this._collapsed[id];
        try {
          localStorage.setItem(`scorte-scadenze:${this._config.entity}`, JSON.stringify(this._collapsed));
        } catch (_e) {
          /* archiviazione non disponibile: lo stato resta per la sessione */
        }
        this._render();
        break;
      case "add":
        this.openDialog("form", null);
        break;
      case "detail":
        this.openDialog("detail", id);
        break;
      case "buy":
        this.openDialog("buy", id);
        break;
      case "use":
        this.call("consumo", { item_id: id, quantita: 1 }, id);
        break;
      case "lot-open":
        this.call("apri", { item_id: id, confezione: lot }, `${id}:${lot}`);
        break;
      case "lot-remove":
        this.call("togli_confezione", { item_id: id, confezione: lot }, `${id}:${lot}`);
        break;
      case "done":
        this.done(id);
        break;
      default:
    }
  }

  done(id) {
    if (this._config.conferma && this._confirm !== id) {
      this._confirm = id;
      this._render();
      this._dialog?.refresh();
      clearTimeout(this._confirmTimer);
      this._confirmTimer = setTimeout(() => {
        this._confirm = null;
        this._render();
        this._dialog?.refresh();
      }, 4000);
      return;
    }
    this._confirm = null;
    this.call("fatto", { item_id: id }, id);
  }
}

// ---------------------------------------------------------------- finestra

class SsDialog {
  constructor(card) {
    this.card = card;
    this.host = document.createElement("div");
    this.host.style.cssText = "position:fixed;inset:0;z-index:1000;display:none";
    this.root = this.host.attachShadow({ mode: "open" });
    document.body.appendChild(this.host);
    this.onKey = (e) => e.key === "Escape" && this.close();
  }

  show(view, id) {
    this.view = view; // detail | form | buy | fix
    this.id = id;
    this.kind = id ? this.card.item(id)?.tipo : K_TASK;
    this.mode = null;
    this.error = "";
    this.confirmDelete = false;
    this.saving = false;
    this.values = null;
    this.moreOpen = false;
    this.lastFocus = document.activeElement;
    this.host.style.display = "block";
    document.addEventListener("keydown", this.onKey);
    this.render(true);
  }

  close() {
    this.host.style.display = "none";
    this.root.innerHTML = "";
    this.view = null;
    document.removeEventListener("keydown", this.onKey);
    this.lastFocus?.focus?.();
  }

  // Aggiornamento dai dati: solo la vista dettaglio, i moduli non si toccano mentre scrivi.
  refresh() {
    if (this.view !== "detail") return;
    if (!this.card.item(this.id)) return this.close();
    this.render(false);
  }

  render(focus) {
    const item = this.id ? this.card.item(this.id) : null;
    let title;
    let body;
    if (this.view === "detail" && item) [title, body] = [item.nome, this.detail(item)];
    else if (this.view === "buy" && item) [title, body] = [`Aggiungi ${item.nome}`, this.buyForm(item)];
    else if (this.view === "fix" && item) [title, body] = [`Correggi ${item.nome}`, this.fixForm(item)];
    else if (this.view === "form") [title, body] = [item ? `Modifica ${item.nome}` : "Nuovo", this.itemForm(item)];
    else return this.close();

    this.root.innerHTML = `
      <style>${DIALOG_STYLE}</style>
      <div class="backdrop" data-act="close"></div>
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="t">
        <header>
          <h2 id="t">${esc(title)}</h2>
          <button class="x" data-act="close" aria-label="Chiudi"><ha-icon icon="mdi:close"></ha-icon></button>
        </header>
        <div class="body">${body}</div>
      </div>`;
    this.root.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", (e) => this.onAction(e)));
    const form = this.root.querySelector("form");
    if (form) {
      form.addEventListener("submit", (e) => this.onSubmit(e));
      form.addEventListener("change", (e) => this.onChange(e));
    }
    if (focus) (this.root.querySelector("form input:not([type=hidden])") || this.root.querySelector(".x"))?.focus();
  }

  // ---- viste

  detail(i) {
    const c = this.card;
    if (i.tipo !== K_STOCK) {
      const confirming = c._confirm === i.id;
      const linked = i.scorta_collegata && c.item(i.scorta_collegata);
      const facts = [
        ["Scadenza", `${dayLabel(i.prossima, true)} (${dueText(i.giorni)})`],
        ...(i.tipo === K_TASK
          ? [
              ["Ogni", `${i.intervallo} ${i.unita_intervallo}`],
              ["Ultima volta", dayLabel(i.ultima, true)],
              ...(linked ? [["Scala da", `${linked.nome} (${fmt(i.quantita_collegata)})`]] : []),
            ]
          : [["Tipo", "Scadenza singola: una volta fatta viene eliminata"]]),
        ...(i.preavviso ? [["Preavviso", `${i.preavviso} giorni`]] : []),
      ];
      return `
        <dl>${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        <div class="row-actions">
          <button class="btn primary wide ${confirming ? "confirm" : ""}" data-act="done" ${c.busy(i.id) ? "disabled" : ""}>
            ${confirming ? "Confermi?" : "Segna come fatto"}</button>
        </div>
        ${this.footer()}`;
    }
    const lots = i.confezioni || [];
    const facts = [
      ["Soglia di riordino", `${fmt(i.soglia)}${unitText(i.unita)}`],
      ...(i.modalita === "consumo" ? [["Consumo", `${fmt(i.consumo)}${unitText(i.unita)} al giorno`]] : []),
      ...(i.autonomia !== null && i.autonomia !== undefined ? [["Autonomia", `circa ${fmt(i.autonomia)} giorni`]] : []),
      ...(i.dopo_apertura ? [["Dopo l'apertura", `entro ${i.dopo_apertura} giorni`]] : []),
    ];
    return `
      <div class="big ${i.sotto_soglia ? "low" : ""}">${fmt(i.giacenza)}<small>${unitText(i.unita)}</small></div>
      <div class="row-actions">
        <button class="btn primary" data-act="buy">+ Aggiungi</button>
        ${i.modalita === "pezzi" ? `<button class="btn" data-act="use" ${i.giacenza <= 0 ? "disabled" : ""}>−1</button>` : ""}
        <button class="btn" data-act="fix">Correggi</button>
      </div>
      <dl>${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      ${lots.length
        ? `<h3>Confezioni</h3>${lots
            .map((l) => {
              const a = lotAction(l, i);
              const second = a.act === "lot-open" ? `<button class="btn" data-act="lot-remove" data-lot="${l.id}">Finita</button>` : "";
              return `<div class="lot ${l.giorni !== null && l.giorni < 0 ? "late" : l.avviso ? "due" : ""}">
                  <span>${esc(lotSub(l, i))}</span>
                  <span class="lot-actions">${second}<button class="btn" data-act="${a.act}" data-lot="${l.id}"
                    ${c.busy(`${i.id}:${l.id}`) ? "disabled" : ""}>${a.label}</button></span>
                </div>`;
            })
            .join("")}`
        : ""}
      ${i.acquisti?.length
        ? `<h3>Ultimi acquisti</h3><ul class="hist">${i.acquisti
            .map(
              (a) =>
                `<li><span>${dayLabel(a.data, true)}</span><span>${fmt(a.quantita)}${unitText(i.unita)}${
                  a.scadenza ? `, scad. ${dayLabel(a.scadenza, true)}` : ""
                }</span></li>`
            )
            .join("")}</ul>`
        : ""}
      ${this.footer()}`;
  }

  footer() {
    return `
      <footer>
        <button class="btn" data-act="edit">Modifica</button>
        <button class="btn danger ${this.confirmDelete ? "confirm" : ""}" data-act="delete">
          ${this.confirmDelete ? "Conferma eliminazione" : "Elimina"}</button>
      </footer>`;
  }

  buyForm(i) {
    return `
      <form novalidate>
        <div class="grid2">
          ${field("Quantità", `<input name="q" inputmode="decimal" required value="${fmt(i.riordino)}">`, i.unita)}
          ${field("Data acquisto", `<input name="d" type="date" required max="${isoToday()}" value="${isoToday()}">`)}
        </div>
        ${field("Scadenza della confezione", `<input name="x" type="date">`, null, "Facoltativa. Serve per gli avvisi di scadenza.")}
        ${this.formEnd("Registra")}
      </form>`;
  }

  fixForm(i) {
    return `
      <form novalidate>
        ${field("Quantità presente ora", `<input name="q" inputmode="decimal" required value="${fmt(i.giacenza)}">`, i.unita,
          "Usala dopo aver contato. Le confezioni che scadono prima vengono scalate per prime.")}
        ${this.formEnd("Salva")}
      </form>`;
  }

  itemForm(i) {
    const kind = i ? i.tipo : this.kind;
    const v = this.values || {};
    const val = (k, d) => esc(v[k] ?? d ?? "");
    const kindPicker = i
      ? ""
      : seg("tipo", kind, [
          [K_TASK, "Promemoria"],
          [K_ONCE, "Scadenza"],
          [K_STOCK, "Prodotto"],
        ]);
    let fields = "";
    let more = "";
    if (kind === K_TASK) {
      const links = this.card.products().filter((p) => p.id !== i?.id);
      fields = `
        ${field("Nome", `<input name="name" required value="${val("name", i?.nome)}" placeholder="Es. Cambio filtro acquario">`)}
        <div class="grid2">
          ${field("Ogni", `<input name="interval" inputmode="numeric" required value="${val("interval", i?.intervallo ?? 30)}">`)}
          ${field("Unità", `<select name="interval_unit">${opts([["giorni", "giorni"], ["settimane", "settimane"], ["mesi", "mesi"]], v.interval_unit ?? i?.unita_intervallo ?? "giorni")}</select>`)}
        </div>
        ${field("Ultima volta fatto", `<input name="last_done" type="date" required max="${isoToday()}" value="${val("last_done", i?.ultima ?? isoToday())}">`)}`;
      more = `
        ${field("Preavviso", `<input name="preavviso" inputmode="numeric" value="${val("preavviso", i?.preavviso ?? 0)}">`, "giorni prima")}
        ${links.length
          ? `<div class="grid2">
              ${field("Scala dal prodotto", `<select name="linked_stock">${opts([["nessuna", "Nessuno"], ...links.map((p) => [p.id, p.nome])], v.linked_stock ?? i?.scorta_collegata ?? "nessuna")}</select>`)}
              ${field("Quantità", `<input name="linked_qty" inputmode="decimal" value="${val("linked_qty", fmt(i?.quantita_collegata ?? 1))}">`)}
            </div>`
          : ""}`;
    } else if (kind === K_ONCE) {
      fields = `
        ${field("Nome", `<input name="name" required value="${val("name", i?.nome)}" placeholder="Es. Bollo auto">`)}
        <div class="grid2">
          ${field("Data", `<input name="data_scadenza" type="date" required value="${val("data_scadenza", i?.prossima)}">`)}
          ${field("Avvisa", `<input name="preavviso" inputmode="numeric" value="${val("preavviso", i?.preavviso ?? 7)}">`, "giorni prima")}
        </div>`;
    } else {
      const mode = v.mode ?? i?.modalita ?? "pezzi";
      fields = `
        ${field("Nome", `<input name="name" required value="${val("name", i?.nome)}" placeholder="Es. Cialde caffè">`)}
        ${seg("mode", mode, [["pezzi", "A pezzi"], ["consumo", "Consumo giornaliero"]])}
        <p class="hint">${mode === "pezzi" ? "Scali tu quando usi qualcosa (tasto −1)." : "La giacenza cala da sola in base al consumo medio."}</p>
        <div class="grid2">
          ${field(i ? "Quantità attuale" : "Quantità", `<input name="quantity" inputmode="decimal" value="${val("quantity", i ? fmt(i.giacenza) : 0)}">`)}
          ${field("Unità", `<input name="unit" value="${val("unit", i?.unita ?? "pz")}" placeholder="pz, cialde, vasetti">`)}
        </div>
        <div class="grid2">
          ${mode === "consumo" ? field("Consumo al giorno", `<input name="daily_rate" inputmode="decimal" required value="${val("daily_rate", i ? fmt(i.consumo) : "")}">`) : ""}
          ${field("Avvisa sotto", `<input name="threshold" inputmode="decimal" value="${val("threshold", i ? fmt(i.soglia) : 1)}">`)}
        </div>
        <div class="grid2">
          ${i ? "" : field("Scadenza", `<input name="scadenza" type="date" value="${val("scadenza", "")}">`)}
          ${field("Aperto, consumare entro", `<input name="dopo_apertura" inputmode="numeric" value="${val("dopo_apertura", i?.dopo_apertura || "")}" placeholder="—">`, "giorni")}
        </div>`;
      more = `
        <div class="grid2">
          ${field("Quantità di riordino", `<input name="riordino" inputmode="decimal" value="${val("riordino", i ? fmt(i.riordino) : 1)}">`)}
          ${field("Avviso scadenza", `<input name="preavviso_scadenza" inputmode="numeric" value="${val("preavviso_scadenza", i?.preavviso_scadenza ?? 2)}">`, "giorni prima")}
        </div>`;
    }
    const icon = v.icon ?? i?.icona ?? ICONS[kind][0];
    more += `
      <span class="lbl">Icona</span>
      <div class="icons">${ICONS[kind]
        .map(
          (ic) =>
            `<button type="button" class="ic ${ic === icon ? "on" : ""}" data-act="icon" data-icon="${ic}" aria-label="${ic}"
              aria-pressed="${ic === icon}"><ha-icon icon="${ic}"></ha-icon></button>`
        )
        .join("")}</div>
      <input name="icon" value="${esc(icon)}" aria-label="Icona personalizzata (mdi:…)">`;
    return `
      <form novalidate>
        ${kindPicker}
        ${fields}
        <details ${this.moreOpen ? "open" : ""}><summary>Altre opzioni</summary>${more}</details>
        ${this.formEnd(i ? "Salva" : "Aggiungi")}
      </form>`;
  }

  formEnd(label) {
    return `
      ${this.error ? `<p class="err" role="alert">${esc(this.error)}</p>` : ""}
      <div class="form-actions">
        <button type="button" class="btn" data-act="${this.view === "form" && !this.id ? "close" : "back"}">Annulla</button>
        <button type="submit" class="btn primary" ${this.saving ? "disabled" : ""}>${this.saving ? "…" : label}</button>
      </div>`;
  }

  // ---- eventi

  snapshot() {
    const form = this.root.querySelector("form");
    if (!form) return;
    this.values = Object.fromEntries(new FormData(form).entries());
    this.moreOpen = form.querySelector("details")?.open;
  }

  onChange(e) {
    // Il cambio di tipo o di calcolo mostra campi diversi: ridisegna mantenendo i valori.
    if (e.target.name === "tipo" || e.target.name === "mode") {
      this.snapshot();
      if (e.target.name === "tipo") {
        this.kind = e.target.value;
        delete this.values.icon;
      }
      this.render(false);
    }
  }

  async onAction(e) {
    const el = e.currentTarget;
    const { act, lot } = el.dataset;
    const c = this.card;
    switch (act) {
      case "close":
        return this.close();
      case "back":
        this.values = null;
        this.view = this.id ? "detail" : null;
        return this.view ? this.render(true) : this.close();
      case "edit":
        this.values = null;
        this.view = "form";
        return this.render(true);
      case "buy":
      case "fix":
        this.error = "";
        this.view = act;
        return this.render(true);
      case "use":
        return c.call("consumo", { item_id: this.id, quantita: 1 }, this.id);
      case "done":
        if (c._config.conferma && c._confirm !== this.id) return c.done(this.id);
        c._confirm = null;
        if (await c.call("fatto", { item_id: this.id }, this.id) && c.item(this.id)?.tipo !== K_TASK) this.close();
        return undefined;
      case "lot-open":
        return c.call("apri", { item_id: this.id, confezione: lot }, `${this.id}:${lot}`);
      case "lot-remove":
        return c.call("togli_confezione", { item_id: this.id, confezione: lot }, `${this.id}:${lot}`);
      case "icon":
        this.root.querySelectorAll(".ic").forEach((b) => {
          b.classList.toggle("on", b === el);
          b.setAttribute("aria-pressed", b === el);
        });
        this.root.querySelector("input[name=icon]").value = el.dataset.icon;
        return undefined;
      case "delete":
        if (!this.confirmDelete) {
          this.confirmDelete = true;
          return this.render(false);
        }
        try {
          await c.ws({ type: "elimina", data: { item_id: this.id } });
          c.toast("Eliminato");
          this.close();
        } catch (err) {
          c.toast(`Eliminazione non riuscita: ${err.message ?? err}`);
        }
        return undefined;
      default:
        return undefined;
    }
  }

  async onSubmit(e) {
    e.preventDefault();
    this.snapshot();
    const v = this.values;
    const c = this.card;
    this.error = "";

    if (this.view === "buy" || this.view === "fix") {
      const q = num(v.q);
      if (q === null || q < 0 || (this.view === "buy" && q === 0)) {
        this.error = "Inserisci una quantità valida.";
        return this.render(false);
      }
      const ok =
        this.view === "buy"
          ? await c.call(
              "acquisto",
              {
                item_id: this.id,
                quantita: q,
                ...(v.d && v.d !== isoToday() ? { data: v.d } : {}),
                ...(v.x ? { scadenza: v.x } : {}),
              },
              this.id
            )
          : await c.call("imposta_giacenza", { item_id: this.id, quantita: q }, this.id);
      if (ok) {
        this.view = "detail";
        this.render(true);
      }
      return undefined;
    }

    // Promemoria / scadenza / prodotto
    const kind = this.id ? c.item(this.id).tipo : this.kind;
    const dati = { name: (v.name || "").trim(), icon: v.icon || undefined };
    const n = (k) => (v[k] === undefined || v[k] === "" ? undefined : num(v[k]));
    if (kind === K_TASK) {
      Object.assign(dati, {
        interval: n("interval"),
        interval_unit: v.interval_unit,
        last_done: v.last_done,
        preavviso: n("preavviso") ?? 0,
        linked_stock: v.linked_stock || "nessuna",
        linked_qty: n("linked_qty") ?? 1,
      });
    } else if (kind === K_ONCE) {
      Object.assign(dati, { data_scadenza: v.data_scadenza, preavviso: n("preavviso") ?? 0 });
    } else {
      Object.assign(dati, {
        mode: v.mode,
        unit: v.unit,
        quantity: n("quantity") ?? 0,
        daily_rate: n("daily_rate") ?? 0,
        threshold: n("threshold") ?? 0,
        riordino: n("riordino") ?? 1,
        dopo_apertura: n("dopo_apertura") ?? 0,
        preavviso_scadenza: n("preavviso_scadenza") ?? 2,
        ...(v.scadenza ? { scadenza: v.scadenza } : {}),
      });
    }
    if (!dati.name) this.error = "Inserisci un nome.";
    else if (kind === K_TASK && !(dati.interval >= 1)) this.error = "Indica ogni quanto va fatto.";
    else if (kind === K_TASK && !dati.last_done) this.error = "Indica l'ultima volta in cui è stato fatto.";
    else if (kind === K_ONCE && !dati.data_scadenza) this.error = "Indica la data di scadenza.";
    else if (kind === K_STOCK && dati.mode === "consumo" && !(dati.daily_rate > 0))
      this.error = "Indica il consumo medio giornaliero.";
    if (this.error) return this.render(false);

    this.saving = true;
    this.render(false);
    try {
      const res = await c.ws({
        type: "salva",
        data: { tipo: kind, dati, ...(this.id ? { item_id: this.id } : {}) },
      });
      this.saving = false;
      this.values = null;
      c.toast(this.id ? "Salvato" : "Aggiunto");
      this.id = res.item_id;
      this.view = "detail";
      // I dati arrivano con il prossimo aggiornamento di stato: chiudi se non ancora presenti.
      if (c.item(this.id)) this.render(true);
      else this.waitAndShow();
    } catch (err) {
      this.saving = false;
      this.error = err.message ?? String(err);
      this.render(false);
    }
    return undefined;
  }

  waitAndShow() {
    this.root.querySelector(".body").innerHTML = `<p class="hint">Salvato.</p>`;
    let tries = 0;
    const t = setInterval(() => {
      if (this.view !== "detail") return clearInterval(t);
      if (this.card.item(this.id)) {
        clearInterval(t);
        this.render(true);
      } else if (++tries > 20) {
        clearInterval(t);
        this.close();
      }
      return undefined;
    }, 150);
  }
}

function field(label, control, suffix, hint) {
  return `<label class="field"><span class="lbl">${label}</span>
    <span class="ctl">${control}${suffix ? `<span class="suf">${esc(suffix)}</span>` : ""}</span>
    ${hint ? `<span class="hint">${hint}</span>` : ""}</label>`;
}

function seg(name, value, options) {
  return `<div class="seg" role="radiogroup">${options
    .map(
      ([v, l]) =>
        `<label class="${v === value ? "on" : ""}"><input type="radio" name="${name}" value="${v}" ${v === value ? "checked" : ""}><span>${l}</span></label>`
    )
    .join("")}</div>`;
}

function opts(list, selected) {
  return list.map(([v, l]) => `<option value="${esc(v)}" ${v === selected ? "selected" : ""}>${esc(l)}</option>`).join("");
}

// ---------------------------------------------------------------- stili

const COMMON = `
  :host { --ok: var(--success-color, #2e7d32); --due: var(--warning-color, #e09100); --late: var(--error-color, #c62828);
          --txt: var(--primary-text-color, #212121); --muted: var(--secondary-text-color, #6b6b6b);
          --line: var(--divider-color, rgba(127,127,127,.25)); --accent: var(--primary-color, #03a9f4);
          --on-accent: var(--text-primary-color, #fff); }
  button { font: inherit; color: inherit; }
  .btn { font-size: .875rem; padding: 6px 14px; min-height: 36px; border-radius: 18px; cursor: pointer;
         border: 1px solid var(--line); background: transparent; color: var(--accent); white-space: nowrap; }
  .btn.icon { min-width: 40px; padding: 6px 10px; font-size: 1rem; font-variant-numeric: tabular-nums; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .btn.confirm { background: var(--late); border-color: var(--late); color: #fff; }
  .btn.danger { color: var(--late); }
  .btn:disabled { opacity: .45; cursor: default; }
  button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible, .seg label:focus-within {
    outline: 2px solid var(--accent); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
`;

const CARD_STYLE = `${COMMON}
  ha-card { padding: 14px 16px 8px; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h2 { margin: 0; font-size: 1.25rem; font-weight: 500; color: var(--txt); }
  .add { width: 40px; height: 40px; border-radius: 50%; border: none; cursor: pointer; display: grid; place-items: center;
         background: var(--accent); color: var(--on-accent); }
  .pills { display: flex; gap: 6px; margin: 12px 0 4px; overflow-x: auto; scrollbar-width: none; }
  .pill { border: 1px solid var(--line); background: transparent; border-radius: 16px; padding: 5px 12px; cursor: pointer;
          font-size: .85rem; color: var(--txt); white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
  .pill.on { background: color-mix(in srgb, var(--accent) 14%, transparent); border-color: var(--accent); color: var(--accent); }
  .pill .n { min-width: 18px; height: 18px; border-radius: 9px; padding: 0 5px; font-size: .72rem; display: grid; place-items: center;
             background: var(--late); color: #fff; box-sizing: border-box; }
  h3, .sec-head { margin: 14px 0 2px; font-size: .9rem; font-weight: 500; color: var(--muted); }
  .sec-head { display: flex; width: 100%; align-items: center; gap: 8px; background: none; border: none; padding: 6px 0; cursor: pointer; text-align: left; }
  .sec-head span:first-child { flex: 1; }
  .sec-count { font-variant-numeric: tabular-nums; }
  .sec-head ha-icon { --mdc-icon-size: 20px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-top: 1px solid var(--line); }
  section > :is(h3, .sec-head) + .row { border-top: none; }
  .main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; background: none; border: none; padding: 2px 0;
          text-align: left; cursor: pointer; }
  .badge { flex: none; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
           background: color-mix(in srgb, var(--muted) 12%, transparent); color: var(--muted); }
  .due .badge { background: color-mix(in srgb, var(--due) 18%, transparent); color: var(--due); }
  .late .badge, .low .badge { background: color-mix(in srgb, var(--late) 15%, transparent); color: var(--late); }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name { font-size: 1rem; color: var(--txt); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font-size: .82rem; color: var(--muted); margin-top: 1px; }
  .late .sub { color: var(--late); }
  .qty { flex: none; font-size: 1.4rem; color: var(--txt); font-variant-numeric: tabular-nums; }
  .qty small { font-size: .78rem; color: var(--muted); margin-left: 2px; }
  .low .qty { color: var(--late); }
  .gauge { position: relative; display: block; height: 5px; border-radius: 3px; margin: 5px 0 1px;
           background: color-mix(in srgb, var(--muted) 18%, transparent); }
  .fill { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: var(--ok); transition: width .4s ease; }
  .low .fill { background: var(--late); }
  .tick { position: absolute; top: -3px; width: 2px; height: 11px; margin-left: -1px; border-radius: 1px; background: var(--txt); opacity: .5; }
  .actions { flex: none; display: flex; gap: 6px; }
  .empty, .calm { color: var(--muted); margin: 12px 0 8px; line-height: 1.5; }
  .calm { font-size: .9rem; }
`;

const DIALOG_STYLE = `${COMMON}
  :host { font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
  .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.45); animation: fade .15s ease; }
  .sheet { position: fixed; left: 50%; top: 50%; transform: translate(-50%,-50%); width: min(440px, calc(100vw - 24px));
           max-height: calc(100vh - 48px); display: flex; flex-direction: column; border-radius: 16px;
           background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--txt);
           box-shadow: 0 12px 40px rgba(0,0,0,.3); animation: rise .18s ease; }
  @media (max-width: 600px) {
    .sheet { left: 0; right: 0; top: auto; bottom: 0; transform: none; width: auto; max-height: 88vh;
             border-radius: 16px 16px 0 0; padding-bottom: env(safe-area-inset-bottom); }
  }
  @keyframes fade { from { opacity: 0; } }
  @keyframes rise { from { opacity: 0; translate: 0 12px; } }
  header { display: flex; align-items: center; gap: 8px; padding: 14px 8px 6px 20px; }
  h2 { flex: 1; margin: 0; font-size: 1.2rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .x { width: 40px; height: 40px; border-radius: 50%; border: none; background: none; cursor: pointer; color: var(--muted); }
  .body { padding: 4px 20px 18px; overflow-y: auto; }
  h3 { margin: 18px 0 6px; font-size: .9rem; font-weight: 500; color: var(--muted); }
  .big { font-size: 2.4rem; font-variant-numeric: tabular-nums; margin: 2px 0 10px; }
  .big small { font-size: 1rem; color: var(--muted); margin-left: 4px; }
  .big.low { color: var(--late); }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; margin: 14px 0 0; font-size: .92rem; }
  dt { color: var(--muted); } dd { margin: 0; }
  .row-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .wide { flex: 1; }
  .lot { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid var(--line); font-size: .92rem; }
  .lot.due span:first-child { color: var(--due); } .lot.late span:first-child { color: var(--late); }
  .lot-actions { display: flex; gap: 6px; flex: none; }
  .hist { list-style: none; margin: 0; padding: 0; font-size: .9rem; }
  .hist li { display: flex; justify-content: space-between; padding: 4px 0; color: var(--muted); }
  footer { display: flex; justify-content: space-between; gap: 8px; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--line); }
  form { display: flex; flex-direction: column; gap: 12px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .grid2:empty { display: none; }
  .field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .lbl { font-size: .8rem; color: var(--muted); }
  .ctl { display: flex; align-items: center; gap: 6px; }
  .suf { font-size: .8rem; color: var(--muted); white-space: nowrap; }
  input, select { font: inherit; font-size: 1rem; padding: 9px 10px; border-radius: 10px; border: 1px solid var(--line);
                  background: var(--card-background-color, transparent); color: var(--txt); min-width: 0; width: 100%;
                  box-sizing: border-box; color-scheme: light dark; }
  .hint { font-size: .8rem; color: var(--muted); margin: -4px 0 0; line-height: 1.4; }
  .field .hint { margin: 0; }
  .seg { display: flex; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  .seg label { flex: 1; text-align: center; padding: 8px 6px; font-size: .88rem; cursor: pointer; color: var(--muted); }
  .seg label + label { border-left: 1px solid var(--line); }
  .seg label.on { background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); font-weight: 500; }
  .seg input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  details { border-top: 1px solid var(--line); padding-top: 10px; }
  details[open] { display: flex; flex-direction: column; gap: 12px; }
  summary { cursor: pointer; color: var(--accent); font-size: .9rem; }
  .icons { display: flex; flex-wrap: wrap; gap: 6px; }
  .ic { width: 40px; height: 40px; border-radius: 10px; border: 1px solid var(--line); background: none; cursor: pointer; color: var(--muted); }
  .ic.on { border-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .err { color: var(--late); font-size: .9rem; margin: 0; }
  .form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
`;

if (!customElements.get("scorte-scadenze-card")) {
  customElements.define("scorte-scadenze-card", ScorteScadenzeCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "scorte-scadenze-card",
    name: "Scorte e Scadenze",
    description: "Promemoria, scadenze e prodotti: segna come fatto, registra acquisti, aggiungi e modifica.",
    preview: true,
  });
  console.info(`%c SCORTE-SCADENZE-CARD %c v${CARD_VERSION} `, "background:#2e7d32;color:#fff", "");
}
