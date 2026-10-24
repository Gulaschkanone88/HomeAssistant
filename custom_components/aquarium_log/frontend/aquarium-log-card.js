// Aquarium-Tagebuch: Eingabe, Verlauf und Tagebuch als eine Dashboard-Karte.
// Wird von der Integration aquarium_log automatisch geladen, keine Ressource nötig.

const DOMAIN = "aquarium_log";

const EVENT_COLORS = {
  water_change: "#1e88e5",
  fertilizer: "#43a047",
  conditioner: "#00897b",
  filter: "#8d6e63",
  cleaning: "#6d4c41",
  plants: "#7cb342",
  livestock: "#f4511e",
  medication: "#e53935",
  technology: "#757575",
  other: "#9e9e9e",
};

const RANGES = [
  { days: 30, label: "30 Tage" },
  { days: 90, label: "90 Tage" },
  { days: 365, label: "1 Jahr" },
  { days: 0, label: "Alles" },
];

const nf = (value, digits = 2) =>
  // Ohne Tausenderpunkt, damit bearbeitete Werte wieder eindeutig eingelesen werden.
  Number(value).toLocaleString("de-DE", { maximumFractionDigits: digits, useGrouping: false });

const esc = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pad = (n) => String(n).padStart(2, "0");

const toLocalInput = (date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;

const formatDate = (iso) =>
  new Date(iso).toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const parseNumber = (text) => {
  if (text === undefined || text === null || String(text).trim() === "") return null;
  const value = Number(String(text).trim().replace(",", "."));
  return Number.isFinite(value) ? value : NaN;
};

class AquariumLogCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._tab = "add";
    this._range = 90;
    this._mode = "measurement";
    this._form = this._emptyForm();
    this._message = null;
    this._busy = false;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = { days: 90, ...config };
    this._range = this._config.days;
    if (config.default_tab) this._tab = config.default_tab;
  }

  getCardSize() {
    return 8;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  _subscribe() {
    if (this._unsub || !this._hass) return;
    const msg = { type: `${DOMAIN}/subscribe` };
    if (this._config?.entry_id) msg.entry_id = this._config.entry_id;
    this._unsub = this._hass.connection.subscribeMessage((data) => {
      this._data = data;
      this._render();
    }, msg);
    this._unsub.catch((err) => {
      this._unsub = null;
      this._error = err.message || String(err);
      this._render();
    });
  }

  _emptyForm() {
    return {
      itemId: null,
      timestamp: toLocalInput(new Date()),
      values: {},
      eventType: "water_change",
      volume: "",
      percent: "",
      note: "",
    };
  }

  // ---------- Rendering ----------

  _render() {
    const title = this._config?.title ?? this._data?.title ?? "Aquarium";
    let body;
    if (this._error) body = `<div class="msg error">${esc(this._error)}</div>`;
    else if (!this._data) body = `<div class="empty">Lade Daten …</div>`;
    else if (this._tab === "add") body = this._renderForm();
    else if (this._tab === "chart") body = this._renderCharts();
    else body = this._renderJournal();

    const tab = (key, label) =>
      `<button class="tab ${this._tab === key ? "active" : ""}" data-tab="${key}">${label}</button>`;

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title">${esc(title)}</div>
          <div class="tabs">${tab("add", "Erfassen")}${tab("chart", "Verlauf")}${tab("journal", "Tagebuch")}</div>
        </div>
        <div class="content">${body}</div>
      </ha-card>`;
    this._bind();
  }

  _renderForm() {
    const f = this._form;
    const editing = Boolean(f.itemId);
    const msg = this._message
      ? `<div class="msg ${this._message.error ? "error" : "ok"}">${esc(this._message.text)}</div>`
      : "";
    const mode = (key, label) =>
      `<button class="seg ${this._mode === key ? "active" : ""}" data-mode="${key}" ${editing ? "disabled" : ""}>${label}</button>`;

    let fields;
    if (this._mode === "measurement") {
      fields = `<div class="grid">${this._data.parameters
        .map(
          (p) => `
          <label class="field">
            <span>${esc(p.name)}</span>
            <div class="input-unit">
              <input type="text" inputmode="decimal" data-value="${p.key}"
                     value="${esc(f.values[p.key] ?? "")}" placeholder="–" autocomplete="off">
              <span class="unit">${esc(p.unit ?? "")}</span>
            </div>
          </label>`
        )
        .join("")}</div>`;
    } else {
      const options = Object.entries(this._data.event_types)
        .map(([key, label]) => `<option value="${key}" ${f.eventType === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
      fields = `
        <div class="grid">
          <label class="field wide"><span>Art</span><select data-field="eventType">${options}</select></label>
          <label class="field"><span>Menge</span>
            <div class="input-unit"><input type="text" inputmode="decimal" data-field="volume" value="${esc(f.volume)}" placeholder="–"><span class="unit">l</span></div>
          </label>
          <label class="field"><span>Anteil</span>
            <div class="input-unit"><input type="text" inputmode="decimal" data-field="percent" value="${esc(f.percent)}" placeholder="–"><span class="unit">%</span></div>
          </label>
        </div>`;
    }

    return `
      <div class="segments">${mode("measurement", "Wassertest")}${mode("event", "Ereignis")}</div>
      <label class="field wide"><span>Datum und Uhrzeit</span>
        <input type="datetime-local" data-field="timestamp" value="${esc(f.timestamp)}">
      </label>
      ${fields}
      <label class="field wide"><span>Notiz</span>
        <textarea data-field="note" rows="2" placeholder="optional">${esc(f.note)}</textarea>
      </label>
      ${msg}
      <div class="actions">
        ${editing ? `<button class="btn secondary" data-action="cancel">Abbrechen</button>` : ""}
        <button class="btn primary" data-action="save" ${this._busy ? "disabled" : ""}>
          ${editing ? "Änderung speichern" : "Speichern"}
        </button>
      </div>`;
  }

  _rangeItems() {
    const items = this._data.items;
    if (!this._range) return { items, start: null };
    const start = Date.now() - this._range * 86400000;
    return { items: items.filter((i) => Date.parse(i.timestamp) >= start), start };
  }

  _renderCharts() {
    const ranges = RANGES.map(
      (r) => `<button class="seg ${this._range === r.days ? "active" : ""}" data-range="${r.days}">${r.label}</button>`
    ).join("");
    const { items, start } = this._rangeItems();
    const measurements = items.filter((i) => i.kind === "measurement");
    const events = items.filter((i) => i.kind === "event");

    if (!measurements.length && !events.length) {
      return `<div class="segments">${ranges}</div><div class="empty">Keine Einträge im gewählten Zeitraum.</div>`;
    }

    const times = items.map((i) => Date.parse(i.timestamp));
    const t0 = start ?? Math.min(...times);
    let t1 = Math.max(Date.now(), ...times);
    const span = Math.max(t1 - t0, 86400000);

    const charts = this._data.parameters
      .map((p) => {
        const points = measurements
          .filter((m) => m.values[p.key] !== undefined)
          .map((m) => ({ t: Date.parse(m.timestamp), v: m.values[p.key] }));
        if (!points.length) return "";
        return this._chart(p, points, events, t0, t0 + span);
      })
      .join("");

    const usedTypes = [...new Set(events.map((e) => e.event_type))];
    const legend = usedTypes
      .map(
        (t) =>
          `<span class="legend"><i style="background:${EVENT_COLORS[t] ?? "#9e9e9e"}"></i>${esc(this._data.event_types[t] ?? t)}</span>`
      )
      .join("");

    return `
      <div class="segments">${ranges}</div>
      ${legend ? `<div class="legends">${legend}</div>` : ""}
      ${charts || `<div class="empty">Keine Messungen im gewählten Zeitraum.</div>`}`;
  }

  _chart(param, points, events, t0, t1) {
    const W = 600, H = 150, L = 46, R = 10, T = 22, B = 22;
    let vmin = Math.min(...points.map((p) => p.v));
    let vmax = Math.max(...points.map((p) => p.v));
    if (vmin === vmax) {
      const pad = Math.abs(vmin) * 0.1 || 1;
      vmin -= pad;
      vmax += pad;
    } else {
      const pad = (vmax - vmin) * 0.12;
      vmin -= pad;
      vmax += pad;
    }
    if (vmin < 0 && Math.min(...points.map((p) => p.v)) >= 0) vmin = 0;
    const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - vmin) / (vmax - vmin)) * (H - T - B);
    const unit = param.unit ? ` ${param.unit}` : "";

    const grid = [vmin, (vmin + vmax) / 2, vmax]
      .map(
        (v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/>
                <text x="${L - 6}" y="${y(v) + 4}" class="axis" text-anchor="end">${nf(v, 2)}</text>`
      )
      .join("");

    const marks = events
      .map((e) => {
        const ex = x(Date.parse(e.timestamp));
        const color = EVENT_COLORS[e.event_type] ?? "#9e9e9e";
        const label = `${this._data.event_types[e.event_type] ?? e.event_type} – ${formatDate(e.timestamp)}${
          e.volume_liters != null ? ` – ${nf(e.volume_liters)} l` : ""
        }${e.percent != null ? ` (${nf(e.percent)} %)` : ""}${e.note ? ` – ${e.note}` : ""}`;
        return `<g><title>${esc(label)}</title>
          <line x1="${ex}" x2="${ex}" y1="${T}" y2="${H - B}" stroke="${color}" stroke-width="${e.event_type === "water_change" ? 2 : 1.2}"
                ${e.event_type === "water_change" ? "" : 'stroke-dasharray="4 3"'}/>
          <rect x="${ex - 6}" y="${T}" width="12" height="${H - T - B}" fill="transparent"/></g>`;
      })
      .join("");

    const sorted = [...points].sort((a, b) => a.t - b.t);
    const path = sorted.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    const dots = sorted
      .map(
        (p) => `<circle cx="${x(p.t)}" cy="${y(p.v)}" r="4" class="dot">
          <title>${esc(`${nf(p.v)}${unit} – ${formatDate(new Date(p.t).toISOString())}`)}</title></circle>`
      )
      .join("");

    const dateLabel = (t) => new Date(t).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit" });
    const last = sorted[sorted.length - 1];

    return `
      <div class="chart">
        <div class="chart-head">
          <span>${esc(param.name)}</span>
          <span class="latest">${nf(last.v)}${esc(unit)}</span>
        </div>
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(param.name)}">
          ${grid}${marks}
          <path d="${path}" class="line"/>
          ${dots}
          <text x="${L}" y="${H - 5}" class="axis">${dateLabel(t0)}</text>
          <text x="${W - R}" y="${H - 5}" class="axis" text-anchor="end">${dateLabel(t1)}</text>
        </svg>
      </div>`;
  }

  _renderJournal() {
    const items = [...this._data.items].reverse();
    if (!items.length) return `<div class="empty">Noch keine Einträge.</div>`;
    const params = Object.fromEntries(this._data.parameters.map((p) => [p.key, p]));
    return `<div class="journal">${items
      .map((item) => {
        let head, detail;
        if (item.kind === "measurement") {
          head = `<span class="badge measure">Wassertest</span>`;
          detail = Object.entries(item.values)
            .map(([k, v]) => {
              const p = params[k];
              const name = p ? p.name.replace(/\s*\(.*\)/, "") : k.toUpperCase();
              return `<span class="val">${esc(name)} <b>${nf(v)}</b>${p?.unit ? ` ${esc(p.unit)}` : ""}</span>`;
            })
            .join("");
        } else {
          const color = EVENT_COLORS[item.event_type] ?? "#9e9e9e";
          head = `<span class="badge" style="background:${color}">${esc(this._data.event_types[item.event_type] ?? item.event_type)}</span>`;
          detail = [
            item.volume_liters != null ? `<span class="val"><b>${nf(item.volume_liters)}</b> l</span>` : "",
            item.percent != null ? `<span class="val"><b>${nf(item.percent)}</b> %</span>` : "",
          ].join("");
        }
        return `
          <div class="row">
            <div class="row-head">
              ${head}<span class="when">${esc(formatDate(item.timestamp))}</span>
              <span class="spacer"></span>
              <button class="icon" data-edit="${item.id}" title="Bearbeiten">✎</button>
              <button class="icon" data-delete="${item.id}" title="Löschen">✕</button>
            </div>
            ${detail ? `<div class="vals">${detail}</div>` : ""}
            ${item.note ? `<div class="note">${esc(item.note)}</div>` : ""}
          </div>`;
      })
      .join("")}</div>`;
  }

  // ---------- Interaktion ----------

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-tab]").forEach((el) =>
      el.addEventListener("click", () => {
        this._tab = el.dataset.tab;
        this._message = null;
        this._render();
      })
    );
    root.querySelectorAll("[data-mode]").forEach((el) =>
      el.addEventListener("click", () => {
        this._mode = el.dataset.mode;
        this._message = null;
        this._render();
      })
    );
    root.querySelectorAll("[data-range]").forEach((el) =>
      el.addEventListener("click", () => {
        this._range = Number(el.dataset.range);
        this._render();
      })
    );
    root.querySelectorAll("[data-value]").forEach((el) =>
      el.addEventListener("input", () => {
        this._form.values[el.dataset.value] = el.value;
      })
    );
    root.querySelectorAll("[data-field]").forEach((el) =>
      el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
        this._form[el.dataset.field] = el.value;
      })
    );
    root.querySelector('[data-action="save"]')?.addEventListener("click", () => this._save());
    root.querySelector('[data-action="cancel"]')?.addEventListener("click", () => {
      this._form = this._emptyForm();
      this._message = null;
      this._render();
    });
    root.querySelectorAll("[data-delete]").forEach((el) =>
      el.addEventListener("click", () => this._delete(el.dataset.delete))
    );
    root.querySelectorAll("[data-edit]").forEach((el) =>
      el.addEventListener("click", () => this._edit(el.dataset.edit))
    );
  }

  _edit(id) {
    const item = this._data.items.find((i) => i.id === id);
    if (!item) return;
    this._mode = item.kind;
    this._form = {
      itemId: item.id,
      timestamp: toLocalInput(new Date(item.timestamp)),
      values: Object.fromEntries(Object.entries(item.values ?? {}).map(([k, v]) => [k, nf(v, 4)])),
      eventType: item.event_type ?? "water_change",
      volume: item.volume_liters != null ? nf(item.volume_liters, 4) : "",
      percent: item.percent != null ? nf(item.percent, 4) : "",
      note: item.note ?? "",
    };
    this._message = null;
    this._tab = "add";
    this._render();
  }

  async _delete(id) {
    const item = this._data.items.find((i) => i.id === id);
    if (!item) return;
    const label = item.kind === "measurement" ? "Wassertest" : this._data.event_types[item.event_type];
    if (!confirm(`${label} vom ${formatDate(item.timestamp)} endgültig löschen?`)) return;
    try {
      await this._call("delete_item", { item_id: id });
    } catch (err) {
      alert(`Löschen fehlgeschlagen: ${err.message || err}`);
    }
  }

  _call(service, data) {
    if (this._data?.entry_id) data = { config_entry_id: this._data.entry_id, ...data };
    return this._hass.callService(DOMAIN, service, data);
  }

  async _save() {
    const f = this._form;
    const data = {};
    if (!f.timestamp) return this._fail("Bitte Datum und Uhrzeit angeben.");
    const when = new Date(f.timestamp);
    if (Number.isNaN(when.getTime())) return this._fail("Ungültiges Datum.");
    if (when.getTime() > Date.now() + 5 * 60000) return this._fail("Der Zeitpunkt liegt in der Zukunft.");
    data.timestamp = when.toISOString();
    data.note = f.note.trim();

    let service;
    if (this._mode === "measurement") {
      const values = {};
      for (const p of this._data.parameters) {
        const v = parseNumber(f.values[p.key]);
        if (v === null) continue;
        if (Number.isNaN(v) || v < 0 || v > p.max) return this._fail(`${p.name}: ungültiger Wert.`);
        values[p.key] = v;
      }
      if (!Object.keys(values).length) return this._fail("Bitte mindestens einen Wert eintragen.");
      if (f.itemId) {
        service = "update_item";
        data.item_id = f.itemId;
        data.values = values;
      } else {
        service = "add_measurement";
        Object.assign(data, values);
      }
    } else {
      const volume = parseNumber(f.volume);
      const percent = parseNumber(f.percent);
      if (Number.isNaN(volume) || volume < 0) return this._fail("Menge: ungültiger Wert.");
      if (Number.isNaN(percent) || percent < 0 || percent > 100) return this._fail("Anteil: Wert zwischen 0 und 100.");
      data.event_type = f.eventType;
      if (f.itemId) {
        service = "update_item";
        data.item_id = f.itemId;
        data.volume_liters = volume;
        data.percent = percent;
      } else {
        service = "add_event";
        if (volume !== null) data.volume_liters = volume;
        if (percent !== null) data.percent = percent;
      }
    }

    this._busy = true;
    this._render();
    try {
      await this._call(service, data);
      const keepMode = this._mode;
      this._form = this._emptyForm();
      this._mode = keepMode;
      this._message = { text: f.itemId ? "Änderung gespeichert." : "Gespeichert." };
    } catch (err) {
      this._message = { error: true, text: `Speichern fehlgeschlagen: ${err.message || err}` };
    }
    this._busy = false;
    this._render();
  }

  _fail(text) {
    this._message = { error: true, text };
    this._render();
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .header { padding: 16px 16px 0; }
  .title { font-size: 1.3em; font-weight: 500; margin-bottom: 10px; }
  .tabs { display: flex; border-bottom: 1px solid var(--divider-color); }
  .tab { flex: 1; background: none; border: none; padding: 10px 4px; font: inherit; cursor: pointer;
         color: var(--secondary-text-color); border-bottom: 2px solid transparent; }
  .tab.active { color: var(--primary-color); border-bottom-color: var(--primary-color); font-weight: 500; }
  .content { padding: 16px; }
  .segments { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
  .seg { flex: 1; min-width: 70px; padding: 8px; border-radius: 8px; border: 1px solid var(--divider-color);
         background: none; font: inherit; color: var(--primary-text-color); cursor: pointer; }
  .seg.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .seg:disabled { opacity: .5; cursor: default; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin: 10px 0; }
  .field { display: flex; flex-direction: column; gap: 4px; font-size: .85em; color: var(--secondary-text-color); }
  .field.wide { grid-column: 1 / -1; margin-bottom: 4px; }
  input, select, textarea { font: inherit; font-size: 1.1em; padding: 8px 10px; border-radius: 8px; box-sizing: border-box; width: 100%;
         border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
  input:focus, select:focus, textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .input-unit { position: relative; display: flex; align-items: center; }
  .input-unit input { padding-right: 52px; }
  .unit { position: absolute; right: 10px; color: var(--secondary-text-color); font-size: .95em; pointer-events: none; }
  textarea { resize: vertical; }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  .btn { padding: 10px 18px; border-radius: 8px; border: none; font: inherit; font-weight: 500; cursor: pointer; }
  .btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.secondary { background: none; border: 1px solid var(--divider-color); color: var(--primary-text-color); }
  .btn:disabled { opacity: .6; }
  .msg { padding: 8px 12px; border-radius: 8px; margin-top: 10px; }
  .msg.ok { background: rgba(67,160,71,.15); color: var(--success-color, #43a047); }
  .msg.error { background: rgba(219,68,55,.12); color: var(--error-color, #db4437); }
  .empty { color: var(--secondary-text-color); text-align: center; padding: 24px 0; }
  .legends { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 10px; font-size: .85em; color: var(--secondary-text-color); }
  .legend i { display: inline-block; width: 12px; height: 3px; margin-right: 5px; vertical-align: middle; }
  .chart { margin-bottom: 14px; }
  .chart-head { display: flex; justify-content: space-between; font-weight: 500; margin-bottom: 2px; }
  .latest { color: var(--primary-color); }
  svg { width: 100%; height: auto; display: block; }
  svg .grid { stroke: var(--divider-color); stroke-width: 1; }
  svg .axis { fill: var(--secondary-text-color); font-size: 11px; }
  svg .line { fill: none; stroke: var(--primary-color); stroke-width: 2; stroke-linejoin: round; }
  svg .dot { fill: var(--card-background-color); stroke: var(--primary-color); stroke-width: 2; }
  .journal .row { padding: 10px 0; border-bottom: 1px solid var(--divider-color); }
  .journal .row:last-child { border-bottom: none; }
  .row-head { display: flex; align-items: center; gap: 8px; }
  .spacer { flex: 1; }
  .badge { font-size: .8em; padding: 2px 8px; border-radius: 10px; color: #fff; white-space: nowrap; }
  .badge.measure { background: var(--primary-color); }
  .when { font-size: .9em; color: var(--secondary-text-color); }
  .icon { background: none; border: none; cursor: pointer; color: var(--secondary-text-color); font-size: 1.05em; padding: 4px 6px; }
  .vals { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; font-size: .95em; }
  .note { margin-top: 4px; font-size: .9em; color: var(--secondary-text-color); white-space: pre-wrap; }
`;

if (!customElements.get("aquarium-log-card")) {
  customElements.define("aquarium-log-card", AquariumLogCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "aquarium-log-card",
    name: "Aquarium-Tagebuch",
    description: "Wasserwerte und Pflegeereignisse erfassen und im Verlauf anzeigen.",
  });
}
