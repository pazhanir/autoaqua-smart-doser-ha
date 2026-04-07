/**
 * Auto Aqua Smart Doser — Schedule Card
 *
 * A custom Lovelace card for managing recurring dosing schedules.
 * Uses HA services for CRUD and WebSocket for fetching schedule data.
 */

const DOMAIN = "autoaqua_doser";
const CARD_VERSION = "1.0.0";

const DAY_LABELS = [
  { key: "mon", label: "M" },
  { key: "tue", label: "T" },
  { key: "wed", label: "W" },
  { key: "thu", label: "T" },
  { key: "fri", label: "F" },
  { key: "sat", label: "S" },
  { key: "sun", label: "S" },
];

class AutoAquaDoserScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._schedules = [];
    this._activePump = 1;
    this._editing = null; // schedule id being edited, or "new"
    this._formData = this._defaultForm();
    this._loading = false;
    this._error = null;
    this._deleteConfirm = null; // schedule id pending delete confirmation
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._schedules.length && !this._loading) {
      this._fetchSchedules();
    }
  }

  setConfig(config) {
    if (!config.device_id) {
      throw new Error("Please define device_id in card config");
    }
    this._config = config;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return { device_id: "" };
  }

  static getConfigElement() {
    return document.createElement("autoaqua-doser-schedule-card-editor");
  }

  // ── Data ───────────────────────────────────────────────────────────

  async _fetchSchedules() {
    if (!this._hass || !this._config.device_id) return;
    this._loading = true;
    this._error = null;
    this._render();

    try {
      const result = await this._hass.callWS({
        type: `${DOMAIN}/get_schedules`,
        device_id: this._config.device_id,
      });
      this._schedules = result.schedules || [];
    } catch (err) {
      console.error("Failed to fetch schedules:", err);
      this._error = "Failed to load schedules";
      this._schedules = [];
    }
    this._loading = false;
    this._render();
  }

  _schedulesForPump(pump) {
    return this._schedules
      .filter((s) => s.pump === pump)
      .sort((a, b) => a.time.localeCompare(b.time));
  }

  async _callService(service, data) {
    try {
      this._error = null;
      await this._hass.callService(DOMAIN, service, {
        device_id: this._config.device_id,
        ...data,
      });
      // Re-fetch after mutation
      await this._fetchSchedules();
    } catch (err) {
      console.error(`Service ${service} failed:`, err);
      this._error = err.message || `Failed: ${service}`;
      this._render();
    }
  }

  // ── Form ───────────────────────────────────────────────────────────

  _defaultForm() {
    return {
      name: "",
      time: "08:00",
      ml: 5,
      days: [],
      enabled: true,
    };
  }

  _openAddForm() {
    this._editing = "new";
    this._formData = { ...this._defaultForm() };
    this._error = null;
    this._render();
  }

  _openEditForm(schedule) {
    this._editing = schedule.id;
    this._formData = {
      name: schedule.name || "",
      time: schedule.time,
      ml: schedule.ml,
      days: [...schedule.days],
      enabled: schedule.enabled,
    };
    this._error = null;
    this._render();
  }

  _closeForm() {
    this._editing = null;
    this._error = null;
    this._render();
  }

  async _submitForm() {
    const f = this._formData;
    if (this._editing === "new") {
      await this._callService("add_schedule", {
        pump: this._activePump,
        ml: f.ml,
        time: f.time,
        days: f.days,
        enabled: f.enabled,
        name: f.name,
      });
    } else {
      await this._callService("update_schedule", {
        schedule_id: this._editing,
        pump: this._activePump,
        ml: f.ml,
        time: f.time,
        days: f.days,
        enabled: f.enabled,
        name: f.name,
      });
    }
    if (!this._error) {
      this._editing = null;
    }
    this._render();
  }

  async _toggleSchedule(scheduleId) {
    await this._callService("toggle_schedule", { schedule_id: scheduleId });
  }

  async _deleteSchedule(scheduleId) {
    this._deleteConfirm = null;
    await this._callService("remove_schedule", { schedule_id: scheduleId });
  }

  // ── Rendering ──────────────────────────────────────────────────────

  _render() {
    if (!this.shadowRoot) return;

    const pumpSchedules = this._schedulesForPump(this._activePump);
    const isEditing = this._editing !== null;

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card>
        <div class="card-header">
          <div class="header-row">
            <span class="title">Dosing Schedules</span>
          </div>
          ${this._renderPumpTabs()}
        </div>
        <div class="card-content">
          ${this._error ? `<div class="error">${this._escHtml(this._error)}</div>` : ""}
          ${this._loading ? '<div class="loading">Loading schedules...</div>' : ""}
          ${!this._loading && !isEditing ? this._renderScheduleList(pumpSchedules) : ""}
          ${isEditing ? this._renderForm() : ""}
          ${!isEditing && !this._loading ? this._renderAddButton() : ""}
        </div>
      </ha-card>
    `;

    this._attachEventListeners();
  }

  _renderPumpTabs() {
    let tabs = "";
    for (let p = 1; p <= 4; p++) {
      const count = this._schedulesForPump(p).length;
      const active = p === this._activePump ? "active" : "";
      tabs += `<button class="pump-tab ${active}" data-pump="${p}">
        Pump ${p}${count > 0 ? ` <span class="badge">${count}</span>` : ""}
      </button>`;
    }
    return `<div class="pump-tabs">${tabs}</div>`;
  }

  _renderScheduleList(schedules) {
    if (!schedules.length) {
      return `
        <div class="empty-state">
          <div class="empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12,6 12,12 16,14"/>
            </svg>
          </div>
          <div class="empty-text">No schedules for Pump ${this._activePump}</div>
          <div class="empty-hint">Tap + to create a dosing schedule</div>
        </div>
      `;
    }

    return `<div class="schedule-list">${schedules.map((s) => this._renderScheduleRow(s)).join("")}</div>`;
  }

  _renderScheduleRow(s) {
    const dayChips = DAY_LABELS.map((d) => {
      const active =
        s.days.length === 0 || s.days.length === 7 || s.days.includes(d.key);
      return `<span class="day-chip ${active ? "active" : ""}">${d.label}</span>`;
    }).join("");

    const isDaily = s.days.length === 0 || s.days.length === 7;
    const deleteConfirming = this._deleteConfirm === s.id;

    return `
      <div class="schedule-row ${s.enabled ? "" : "disabled"}">
        <div class="schedule-left">
          <div class="schedule-time">${this._escHtml(s.time)}</div>
          <div class="schedule-meta">
            <span class="schedule-ml">${s.ml} ml</span>
            ${s.name ? `<span class="schedule-name">${this._escHtml(s.name)}</span>` : ""}
          </div>
          <div class="schedule-days ${isDaily ? "daily" : ""}">${isDaily ? '<span class="daily-label">Daily</span>' : dayChips}</div>
        </div>
        <div class="schedule-right">
          <label class="toggle-switch">
            <input type="checkbox" ${s.enabled ? "checked" : ""} data-toggle="${s.id}" />
            <span class="toggle-slider"></span>
          </label>
          <button class="icon-btn edit-btn" data-edit="${s.id}" title="Edit">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          ${
            deleteConfirming
              ? `<button class="icon-btn delete-confirm-btn" data-confirm-delete="${s.id}" title="Confirm delete">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20,6 9,17 4,12"/>
                  </svg>
                </button>
                <button class="icon-btn cancel-delete-btn" data-cancel-delete="${s.id}" title="Cancel">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>`
              : `<button class="icon-btn delete-btn" data-delete="${s.id}" title="Delete">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3,6 5,6 21,6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>`
          }
        </div>
      </div>
    `;
  }

  _renderForm() {
    const f = this._formData;
    const isNew = this._editing === "new";

    const dayCheckboxes = DAY_LABELS.map(
      (d) => `
      <label class="day-checkbox ${f.days.includes(d.key) ? "selected" : ""}">
        <input type="checkbox" value="${d.key}" ${f.days.includes(d.key) ? "checked" : ""} data-day-check />
        <span>${d.label}</span>
      </label>
    `
    ).join("");

    return `
      <div class="form-container">
        <div class="form-title">${isNew ? "New Schedule" : "Edit Schedule"}</div>

        <div class="form-row">
          <label>Name (optional)</label>
          <input type="text" class="form-input" id="form-name" value="${this._escAttr(f.name)}" placeholder="e.g. Morning alkalinity" />
        </div>

        <div class="form-row">
          <label>Time</label>
          <input type="time" class="form-input" id="form-time" value="${f.time}" />
        </div>

        <div class="form-row">
          <label>Amount (ml)</label>
          <input type="number" class="form-input" id="form-ml" value="${f.ml}" min="1" max="999" step="1" />
        </div>

        <div class="form-row">
          <label>Days <span class="hint">(none selected = daily)</span></label>
          <div class="day-checkboxes">${dayCheckboxes}</div>
        </div>

        <div class="form-actions">
          <button class="btn btn-cancel" id="form-cancel">Cancel</button>
          <button class="btn btn-save" id="form-save">${isNew ? "Add" : "Save"}</button>
        </div>
      </div>
    `;
  }

  _renderAddButton() {
    return `
      <button class="add-btn" id="add-schedule-btn">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        Add Schedule
      </button>
    `;
  }

  // ── Event handling ─────────────────────────────────────────────────

  _attachEventListeners() {
    const root = this.shadowRoot;

    // Pump tabs
    root.querySelectorAll(".pump-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activePump = parseInt(btn.dataset.pump, 10);
        this._editing = null;
        this._deleteConfirm = null;
        this._error = null;
        this._render();
      });
    });

    // Toggle switches
    root.querySelectorAll("[data-toggle]").forEach((input) => {
      input.addEventListener("change", () => {
        this._toggleSchedule(input.dataset.toggle);
      });
    });

    // Edit buttons
    root.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const s = this._schedules.find((x) => x.id === btn.dataset.edit);
        if (s) this._openEditForm(s);
      });
    });

    // Delete buttons (first click: confirm, second click: delete)
    root.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._deleteConfirm = btn.dataset.delete;
        this._render();
      });
    });

    root.querySelectorAll("[data-confirm-delete]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._deleteSchedule(btn.dataset.confirmDelete);
      });
    });

    root.querySelectorAll("[data-cancel-delete]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._deleteConfirm = null;
        this._render();
      });
    });

    // Add button
    const addBtn = root.getElementById("add-schedule-btn");
    if (addBtn) {
      addBtn.addEventListener("click", () => this._openAddForm());
    }

    // Form events
    const formCancel = root.getElementById("form-cancel");
    if (formCancel) {
      formCancel.addEventListener("click", () => this._closeForm());
    }

    const formSave = root.getElementById("form-save");
    if (formSave) {
      formSave.addEventListener("click", () => {
        // Collect form values
        const name = root.getElementById("form-name")?.value || "";
        const time = root.getElementById("form-time")?.value || "08:00";
        const ml = parseInt(root.getElementById("form-ml")?.value || "5", 10);
        const days = [];
        root.querySelectorAll("[data-day-check]").forEach((cb) => {
          if (cb.checked) days.push(cb.value);
        });

        this._formData = { name, time, ml, days, enabled: this._formData.enabled };
        this._submitForm();
      });
    }

    // Day checkbox visual toggle
    root.querySelectorAll("[data-day-check]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.parentElement.classList.toggle("selected", cb.checked);
      });
    });
  }

  // ── Styles ─────────────────────────────────────────────────────────

  _styles() {
    return `
      :host {
        --primary: var(--primary-color, #03a9f4);
        --primary-text: var(--primary-text-color, #212121);
        --secondary-text: var(--secondary-text-color, #727272);
        --card-bg: var(--ha-card-background, var(--card-background-color, #fff));
        --divider: var(--divider-color, rgba(0,0,0,0.12));
        --error-color: var(--error-color, #db4437);
        --success-color: var(--success-color, #0f9d58);
        --disabled-opacity: 0.45;
      }

      ha-card {
        overflow: hidden;
      }

      .card-header {
        padding: 16px 16px 0;
      }

      .header-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }

      .title {
        font-size: 18px;
        font-weight: 500;
        color: var(--primary-text);
      }

      /* Pump tabs */
      .pump-tabs {
        display: flex;
        gap: 4px;
        border-bottom: 1px solid var(--divider);
        padding-bottom: 0;
      }

      .pump-tab {
        flex: 1;
        padding: 8px 4px 10px;
        border: none;
        background: none;
        color: var(--secondary-text);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
        font-family: inherit;
      }

      .pump-tab:hover {
        color: var(--primary-text);
        background: rgba(0,0,0,0.04);
      }

      .pump-tab.active {
        color: var(--primary);
        border-bottom-color: var(--primary);
      }

      .badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        border-radius: 9px;
        background: var(--primary);
        color: #fff;
        font-size: 11px;
        font-weight: 600;
        margin-left: 4px;
      }

      .card-content {
        padding: 16px;
      }

      /* Error */
      .error {
        background: rgba(219,68,55,0.1);
        border: 1px solid var(--error-color);
        color: var(--error-color);
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 13px;
        margin-bottom: 12px;
      }

      .loading {
        text-align: center;
        color: var(--secondary-text);
        padding: 24px 0;
        font-size: 14px;
      }

      /* Empty state */
      .empty-state {
        text-align: center;
        padding: 32px 16px;
        color: var(--secondary-text);
      }

      .empty-icon {
        opacity: 0.3;
        margin-bottom: 12px;
      }

      .empty-text {
        font-size: 15px;
        font-weight: 500;
        margin-bottom: 4px;
        color: var(--primary-text);
      }

      .empty-hint {
        font-size: 13px;
      }

      /* Schedule list */
      .schedule-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .schedule-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px;
        border-radius: 12px;
        background: var(--card-bg);
        border: 1px solid var(--divider);
        transition: opacity 0.2s;
      }

      .schedule-row.disabled {
        opacity: var(--disabled-opacity);
      }

      .schedule-left {
        flex: 1;
        min-width: 0;
      }

      .schedule-time {
        font-size: 22px;
        font-weight: 600;
        color: var(--primary-text);
        font-variant-numeric: tabular-nums;
        line-height: 1.2;
      }

      .schedule-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 2px;
      }

      .schedule-ml {
        font-size: 13px;
        font-weight: 600;
        color: var(--primary);
      }

      .schedule-name {
        font-size: 12px;
        color: var(--secondary-text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .schedule-days {
        display: flex;
        gap: 3px;
        margin-top: 6px;
      }

      .day-chip {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        font-size: 10px;
        font-weight: 600;
        color: var(--secondary-text);
        background: rgba(0,0,0,0.06);
        transition: all 0.15s;
      }

      .day-chip.active {
        background: var(--primary);
        color: #fff;
      }

      .daily-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--primary);
        padding: 2px 8px;
        background: rgba(3,169,244,0.1);
        border-radius: 10px;
      }

      .schedule-right {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-left: 12px;
        flex-shrink: 0;
      }

      /* Toggle switch */
      .toggle-switch {
        position: relative;
        display: inline-block;
        width: 40px;
        height: 22px;
      }

      .toggle-switch input {
        opacity: 0;
        width: 0;
        height: 0;
      }

      .toggle-slider {
        position: absolute;
        cursor: pointer;
        inset: 0;
        background: rgba(0,0,0,0.2);
        border-radius: 11px;
        transition: background 0.2s;
      }

      .toggle-slider::before {
        content: "";
        position: absolute;
        width: 18px;
        height: 18px;
        left: 2px;
        bottom: 2px;
        background: #fff;
        border-radius: 50%;
        transition: transform 0.2s;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
      }

      .toggle-switch input:checked + .toggle-slider {
        background: var(--primary);
      }

      .toggle-switch input:checked + .toggle-slider::before {
        transform: translateX(18px);
      }

      /* Icon buttons */
      .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border: none;
        background: none;
        cursor: pointer;
        border-radius: 8px;
        color: var(--secondary-text);
        transition: all 0.15s;
        padding: 0;
      }

      .icon-btn:hover {
        background: rgba(0,0,0,0.08);
        color: var(--primary-text);
      }

      .delete-btn:hover {
        color: var(--error-color);
      }

      .delete-confirm-btn {
        color: var(--error-color) !important;
        background: rgba(219,68,55,0.1) !important;
      }

      .cancel-delete-btn:hover {
        color: var(--primary-text);
      }

      /* Add button */
      .add-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        width: 100%;
        padding: 10px;
        margin-top: 8px;
        border: 2px dashed var(--divider);
        border-radius: 12px;
        background: none;
        color: var(--primary);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
      }

      .add-btn:hover {
        border-color: var(--primary);
        background: rgba(3,169,244,0.05);
      }

      /* Form */
      .form-container {
        background: var(--card-bg);
        border: 1px solid var(--divider);
        border-radius: 12px;
        padding: 16px;
      }

      .form-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--primary-text);
        margin-bottom: 16px;
      }

      .form-row {
        margin-bottom: 14px;
      }

      .form-row label {
        display: block;
        font-size: 12px;
        font-weight: 500;
        color: var(--secondary-text);
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .hint {
        text-transform: none;
        font-weight: 400;
        letter-spacing: 0;
        opacity: 0.7;
      }

      .form-input {
        width: 100%;
        padding: 8px 12px;
        border: 1px solid var(--divider);
        border-radius: 8px;
        font-size: 14px;
        color: var(--primary-text);
        background: var(--card-bg);
        box-sizing: border-box;
        font-family: inherit;
        outline: none;
        transition: border-color 0.2s;
      }

      .form-input:focus {
        border-color: var(--primary);
      }

      /* Day checkboxes */
      .day-checkboxes {
        display: flex;
        gap: 4px;
      }

      .day-checkbox {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        border-radius: 50%;
        border: 2px solid var(--divider);
        cursor: pointer;
        transition: all 0.15s;
        font-size: 13px;
        font-weight: 600;
        color: var(--secondary-text);
        user-select: none;
      }

      .day-checkbox input {
        display: none;
      }

      .day-checkbox.selected {
        background: var(--primary);
        border-color: var(--primary);
        color: #fff;
      }

      .day-checkbox:hover:not(.selected) {
        border-color: var(--primary);
        color: var(--primary);
      }

      /* Form actions */
      .form-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
        margin-top: 16px;
      }

      .btn {
        padding: 8px 20px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
      }

      .btn-cancel {
        background: rgba(0,0,0,0.06);
        color: var(--primary-text);
      }

      .btn-cancel:hover {
        background: rgba(0,0,0,0.12);
      }

      .btn-save {
        background: var(--primary);
        color: #fff;
      }

      .btn-save:hover {
        filter: brightness(1.1);
      }
    `;
  }

  // ── Util ───────────────────────────────────────────────────────────

  _escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  _escAttr(str) {
    return str.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
}

// ── Config editor ────────────────────────────────────────────────────

class AutoAquaDoserScheduleCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        .editor {
          padding: 16px;
        }
        label {
          display: block;
          font-weight: 500;
          margin-bottom: 4px;
        }
        input {
          width: 100%;
          padding: 8px;
          border: 1px solid #ccc;
          border-radius: 4px;
          font-size: 14px;
          box-sizing: border-box;
        }
        .hint {
          font-size: 12px;
          color: #666;
          margin-top: 4px;
        }
      </style>
      <div class="editor">
        <label>Device ID</label>
        <input type="text" id="device_id" value="${this._config.device_id || ""}" placeholder="e.g. 34B7DA28DE69" />
        <div class="hint">The MAC / device ID of your Auto Aqua Smart Doser</div>
      </div>
    `;

    this.shadowRoot.getElementById("device_id").addEventListener("input", (e) => {
      this._config = { ...this._config, device_id: e.target.value };
      const event = new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    });
  }
}

// ── Register ─────────────────────────────────────────────────────────

customElements.define(
  "autoaqua-doser-schedule-card",
  AutoAquaDoserScheduleCard
);
customElements.define(
  "autoaqua-doser-schedule-card-editor",
  AutoAquaDoserScheduleCardEditor
);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "autoaqua-doser-schedule-card",
  name: "Auto Aqua Doser Schedule",
  description: "Manage recurring dosing schedules for the Auto Aqua Smart Doser 4",
  preview: false,
  documentationURL: "https://github.com/pazhanir/autoaqua-smart-doser-ha",
});

console.info(
  `%c AUTO-AQUA-DOSER-SCHEDULE-CARD %c v${CARD_VERSION} `,
  "background: #03a9f4; color: #fff; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "background: #444; color: #fff; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
