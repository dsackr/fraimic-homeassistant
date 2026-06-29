/**
 * Fraimic Panel
 * Sidebar panel that auto-discovers all Fraimic frames and lets you send
 * images to any of them — no manual card configuration required.
 */

(function () {
  'use strict';

  const PANEL_VERSION = '0.1.5';

  // -------------------------------------------------------------------------
  // Styles
  // -------------------------------------------------------------------------

  const CSS = `
    :host {
      display: block;
      padding: 24px;
      background: var(--primary-background-color);
      min-height: 100%;
      box-sizing: border-box;
    }

    h1 {
      margin: 0 0 24px;
      font-size: 20px;
      font-weight: 600;
      color: var(--primary-text-color);
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
    }

    .card {
      background: var(--card-background-color, #fff);
      border-radius: 12px;
      padding: 16px;
      box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.1));
    }

    /* ---- card header ---- */
    .card-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }
    .frame-icon {
      width: 44px; height: 44px;
      border-radius: 10px;
      background: var(--primary-color, #3b82f6);
      display: flex; align-items: center; justify-content: center;
      font-size: 22px;
      flex-shrink: 0;
    }
    .frame-meta { flex: 1; min-width: 0; }
    .frame-name {
      font-size: 15px;
      font-weight: 600;
      color: var(--primary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .frame-status {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 3px;
    }
    .dot-on  { color: var(--success-color,  #16a34a); }
    .dot-off { color: var(--error-color,    #dc2626); }

    /* ---- preview ---- */
    .preview {
      display: none;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--divider-color, rgba(0,0,0,.1));
      background: var(--secondary-background-color, #f1f5f9);
      margin-bottom: 12px;
      text-align: center;
    }
    .preview img {
      display: block;
      width: 100%;
      max-height: 200px;
      object-fit: contain;
    }
    .preview-name {
      padding: 4px 8px;
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* ---- buttons ---- */
    .btns { display: flex; gap: 8px; }
    button {
      flex: 1;
      padding: 9px 12px;
      border: none;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: opacity .15s, transform .1s;
    }
    button:active:not(:disabled) { transform: scale(.97); }
    button:disabled { opacity: .45; cursor: default; }

    .btn-primary {
      background: var(--primary-color, #3b82f6);
      color: #fff;
    }
    .btn-ghost {
      background: var(--secondary-background-color, #e2e8f0);
      color: var(--primary-text-color);
      flex: 0 0 auto;
      padding-left: 14px;
      padding-right: 14px;
    }

    /* ---- feedback ---- */
    .feedback {
      display: none;
      margin-top: 8px;
      padding: 7px 10px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.4;
    }
    .feedback.ok  { background: rgba(22,163,74,.1);  color: var(--success-color, #15803d); }
    .feedback.err { background: rgba(220,38,38,.08); color: var(--error-color,   #b91c1c); }

    input[type="file"] { display: none; }

    /* ---- empty state ---- */
    .empty {
      text-align: center;
      padding: 60px 24px;
      color: var(--secondary-text-color);
    }
    .empty h2 { margin: 12px 0 8px; font-size: 18px; color: var(--primary-text-color); }
    .empty p  { margin: 0; font-size: 14px; line-height: 1.6; }
  `;

  // -------------------------------------------------------------------------
  // Panel element
  // -------------------------------------------------------------------------

  class FraimicPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._frames   = [];   // [{ title, entityId, deviceId }]
      this._loaded   = false;
      this._stateMap = {};   // entityId → { battery, available }
      this._cards    = {};   // entityId → { dom refs + state }
    }

    // HA sets this whenever state changes.
    set hass(hass) {
      this._hass = hass;

      if (!this._loaded) {
        this._loaded = true;
        this._init();
      } else {
        this._tickAllStatus();
      }
    }

    // -----------------------------------------------------------------------

    async _init() {
      this._buildShell();
      await this._discoverFrames();
      this._renderFrames();
    }

    _buildShell() {
      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>
        <h1>🖼 Fraimic Frames</h1>
        <div class="grid" id="grid">
          <div class="empty">
            <div style="font-size:36px">⏳</div>
            <h2>Discovering frames…</h2>
          </div>
        </div>
      `;
    }

    // -----------------------------------------------------------------------
    // Frame discovery via HA WebSocket APIs
    // -----------------------------------------------------------------------

    async _discoverFrames() {
      try {
        const [entries, devices, entities] = await Promise.all([
          this._hass.callWS({ type: 'config_entries/list', domain: 'fraimic' }),
          this._hass.callWS({ type: 'config/device_registry/list' }),
          this._hass.callWS({ type: 'config/entity_registry/list' }),
        ]);

        this._frames = entries.map(entry => {
          const device = devices.find(d =>
            d.config_entries && d.config_entries.includes(entry.entry_id)
          );
          const batteryEntity = entities.find(e =>
            device && e.device_id === device.id &&
            (e.unique_id || '').endsWith('_battery')
          );
          return {
            title:    entry.title,
            entityId: batteryEntity ? batteryEntity.entity_id : null,
            deviceId: device ? device.id : null,
          };
        }).filter(f => f.entityId); // only frames we can identify
      } catch (err) {
        console.error('[fraimic-panel] discovery failed:', err);
        this._frames = [];
      }
    }

    // -----------------------------------------------------------------------
    // Render
    // -----------------------------------------------------------------------

    _renderFrames() {
      const grid = this.shadowRoot.getElementById('grid');

      if (!this._frames.length) {
        grid.innerHTML = `
          <div class="empty">
            <div style="font-size:48px">🖼</div>
            <h2>No frames found</h2>
            <p>Go to <strong>Settings → Integrations → + Add Integration</strong>
               and search for <strong>Fraimic</strong> to set up your frames.</p>
          </div>
        `;
        return;
      }

      grid.innerHTML = '';
      this._cards = {};

      for (const frame of this._frames) {
        const card = this._buildCard(frame);
        grid.appendChild(card.el);
        this._cards[frame.entityId] = card;
      }

      this._tickAllStatus();
    }

    _buildCard(frame) {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = `
        <div class="card-header">
          <div class="frame-icon">🖼</div>
          <div class="frame-meta">
            <div class="frame-name">${this._esc(frame.title)}</div>
            <div class="frame-status" id="status-${this._sid(frame.entityId)}"></div>
          </div>
        </div>
        <div class="preview" id="preview-${this._sid(frame.entityId)}">
          <img id="img-${this._sid(frame.entityId)}" alt="preview" />
          <div class="preview-name" id="imgname-${this._sid(frame.entityId)}"></div>
        </div>
        <div class="btns">
          <button class="btn-primary" id="pick-${this._sid(frame.entityId)}">📷 Send Image</button>
          <button class="btn-primary" id="send-${this._sid(frame.entityId)}" style="display:none">⬆ Send to Frame</button>
          <button class="btn-ghost"   id="cancel-${this._sid(frame.entityId)}" style="display:none">✕</button>
        </div>
        <div class="feedback" id="fb-${this._sid(frame.entityId)}"></div>
        <input type="file" id="file-${this._sid(frame.entityId)}"
          accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/*">
      `;

      const sid = this._sid(frame.entityId);

      el.querySelector(`#pick-${sid}`).addEventListener('click', () => {
        el.querySelector(`#file-${sid}`).click();
      });

      el.querySelector(`#file-${sid}`).addEventListener('change', e => {
        const file = e.target.files && e.target.files[0];
        if (file) this._onFile(frame.entityId, file, el);
      });

      el.querySelector(`#send-${sid}`).addEventListener('click', () => {
        this._send(frame.entityId, el);
      });

      el.querySelector(`#cancel-${sid}`).addEventListener('click', () => {
        this._resetCard(frame.entityId, el);
      });

      return { el, file: null, previewUrl: null };
    }

    // -----------------------------------------------------------------------
    // Status refresh
    // -----------------------------------------------------------------------

    _tickAllStatus() {
      for (const frame of this._frames) {
        this._tickStatus(frame);
      }
    }

    _tickStatus(frame) {
      const sid = this._sid(frame.entityId);
      const statusEl = this.shadowRoot.getElementById(`status-${sid}`);
      if (!statusEl) return;

      const state = this._hass.states[frame.entityId];
      if (!state || state.state === 'unavailable' || state.state === 'unknown') {
        statusEl.innerHTML = '<span class="dot-off">● Offline</span>';
        return;
      }
      const pct = parseFloat(state.state);
      const bat = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'} ${pct}%&nbsp; `;
      statusEl.innerHTML = `${bat}<span class="dot-on">● Online</span>`;
    }

    // -----------------------------------------------------------------------
    // File selection → preview
    // -----------------------------------------------------------------------

    _onFile(entityId, file, el) {
      const sid = this._sid(entityId);
      const card = this._cards[entityId];

      // Release previous preview URL.
      if (card.previewUrl) URL.revokeObjectURL(card.previewUrl);
      card.previewUrl = URL.createObjectURL(file);
      card.file = file;

      el.querySelector(`#img-${sid}`).src = card.previewUrl;
      el.querySelector(`#imgname-${sid}`).textContent = file.name;
      el.querySelector(`#preview-${sid}`).style.display = 'block';
      el.querySelector(`#pick-${sid}`).style.display   = 'none';
      el.querySelector(`#send-${sid}`).style.display   = '';
      el.querySelector(`#cancel-${sid}`).style.display = '';
      this._hideFb(sid, el);
    }

    // -----------------------------------------------------------------------
    // Send image
    // -----------------------------------------------------------------------

    async _send(entityId, el) {
      const sid  = this._sid(entityId);
      const card = this._cards[entityId];
      if (!card || !card.file) return;

      const btnSend   = el.querySelector(`#send-${sid}`);
      const btnCancel = el.querySelector(`#cancel-${sid}`);
      btnSend.textContent = '⏳ Sending…';
      btnSend.disabled    = true;
      btnCancel.disabled  = true;

      const form = new FormData();
      form.append('entity_id', entityId);
      form.append('image', card.file);

      let token;
      try { token = this._hass.auth.data.access_token; } catch (_) {}

      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const resp = await fetch('/api/fraimic/send_image', {
          method: 'POST', headers, body: form,
        });
        let result;
        try { result = await resp.json(); } catch (_) { result = {}; }

        if (resp.ok && result.success) {
          this._showFb(sid, el, 'ok', '✓ Image sent!');
          setTimeout(() => this._resetCard(entityId, el), 3000);
        } else {
          const msg = result.message || resp.statusText || `HTTP ${resp.status}`;
          this._showFb(sid, el, 'err', `Failed: ${msg}`);
          btnSend.textContent = '⬆ Send to Frame';
          btnSend.disabled    = false;
          btnCancel.disabled  = false;
        }
      } catch (err) {
        this._showFb(sid, el, 'err', `Network error: ${err.message}`);
        btnSend.textContent = '⬆ Send to Frame';
        btnSend.disabled    = false;
        btnCancel.disabled  = false;
      }
    }

    // -----------------------------------------------------------------------
    // Reset card to idle state
    // -----------------------------------------------------------------------

    _resetCard(entityId, el) {
      const sid  = this._sid(entityId);
      const card = this._cards[entityId];

      if (card) {
        if (card.previewUrl) { URL.revokeObjectURL(card.previewUrl); card.previewUrl = null; }
        card.file = null;
      }

      const fi = el.querySelector(`#file-${sid}`);
      if (fi) fi.value = '';
      const img = el.querySelector(`#img-${sid}`);
      if (img) img.src = '';

      el.querySelector(`#preview-${sid}`).style.display = 'none';
      el.querySelector(`#pick-${sid}`).style.display    = '';
      el.querySelector(`#send-${sid}`).style.display    = 'none';
      el.querySelector(`#cancel-${sid}`).style.display  = 'none';

      const btnSend = el.querySelector(`#send-${sid}`);
      btnSend.textContent = '⬆ Send to Frame';
      btnSend.disabled    = false;
      el.querySelector(`#cancel-${sid}`).disabled = false;

      this._hideFb(sid, el);
    }

    // -----------------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------------

    _sid(entityId) {
      // Safe CSS/DOM ID segment from an entity_id.
      return (entityId || '').replace(/[^a-z0-9]/gi, '_');
    }

    _esc(str) {
      return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    _showFb(sid, el, type, msg) {
      const fb = el.querySelector(`#fb-${sid}`);
      fb.className     = `feedback ${type}`;
      fb.textContent   = msg;
      fb.style.display = 'block';
    }

    _hideFb(sid, el) {
      const fb = el.querySelector(`#fb-${sid}`);
      if (fb) fb.style.display = 'none';
    }
  }

  customElements.define('fraimic-panel', FraimicPanel);

  console.info(
    '%c FRAIMIC-PANEL %c v' + PANEL_VERSION + ' ',
    'background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px 0 0 3px;font-weight:600',
    'background:#1e293b;color:#fff;padding:2px 6px;border-radius:0 3px 3px 0',
  );
})();
