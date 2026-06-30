/**
 * Fraimic Panel
 * Sidebar panel that auto-discovers all Fraimic frames and lets you send
 * images to any of them — no manual card configuration required.
 */

(function () {
  'use strict';

  const PANEL_VERSION = '0.2.2';

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

    /* ---- library ---- */
    h2.section-title {
      margin: 36px 0 16px;
      font-size: 18px;
      font-weight: 600;
      color: var(--primary-text-color);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .lib-toolbar {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .lib-backend {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--secondary-text-color);
    }
    .lib-backend select, .lib-card select {
      padding: 6px 8px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, rgba(0,0,0,.15));
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-size: 13px;
    }
    .lib-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 16px;
    }
    .lib-thumb {
      border-radius: 8px;
      overflow: hidden;
      background: var(--secondary-background-color, #f1f5f9);
      margin-bottom: 10px;
      height: 140px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .lib-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .lib-card .btns select { flex: 1; }
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

      this._library      = [];        // [{ image_id, filename, content_type, resolutions }]
      this._backend       = 'local';  // active library storage backend
      this._libThumbUrls  = {};       // image_id → blob: URL (revoked on re-render)
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
      this._wireLibraryToolbar();
      await this._discoverFrames();
      this._renderFrames();
      await this._loadBackendSettings();
      await this._loadLibrary();
      this._renderLibrary();
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

        <h2 class="section-title">📚 Library</h2>
        <div class="lib-toolbar">
          <div class="lib-backend">
            <label for="backend-select">Storage:</label>
            <select id="backend-select">
              <option value="local">Local (this Home Assistant)</option>
              <option value="google_drive">Google Drive</option>
              <option value="dropbox">Dropbox</option>
            </select>
          </div>
          <button class="btn-primary" id="lib-upload-btn"
            style="flex:0 0 auto;padding-left:14px;padding-right:14px">⬆ Upload to Library</button>
          <input type="file" id="lib-upload-input"
            accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/*">
        </div>
        <div class="feedback" id="lib-fb"></div>
        <div class="lib-grid" id="lib-grid">
          <div class="empty">
            <div style="font-size:36px">⏳</div>
            <h2>Loading library…</h2>
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
          this._hass.callWS({ type: 'config_entries/get', domain: 'fraimic' }),
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

      try {
        const resp = await fetch('/api/fraimic/send_image', {
          method: 'POST', headers: this._authHeaders(), body: form,
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
    // Library: toolbar wiring
    // -----------------------------------------------------------------------

    _wireLibraryToolbar() {
      const uploadBtn     = this.shadowRoot.getElementById('lib-upload-btn');
      const uploadInput   = this.shadowRoot.getElementById('lib-upload-input');
      const backendSelect = this.shadowRoot.getElementById('backend-select');

      uploadBtn.addEventListener('click', () => uploadInput.click());

      uploadInput.addEventListener('change', e => {
        const file = e.target.files && e.target.files[0];
        if (file) this._onLibraryFile(file);
      });

      backendSelect.addEventListener('change', e => this._onBackendChange(e));
    }

    // -----------------------------------------------------------------------
    // Library: backend settings
    // -----------------------------------------------------------------------

    async _loadBackendSettings() {
      try {
        const resp = await fetch('/api/fraimic/library/settings', { headers: this._authHeaders() });
        const result = await resp.json();
        this._backend = result.backend || 'local';
      } catch (err) {
        console.warn('[fraimic-panel] could not load library settings:', err);
      }
      const sel = this.shadowRoot.getElementById('backend-select');
      if (sel) sel.value = this._backend;
    }

    async _onBackendChange(e) {
      const fb          = this.shadowRoot.getElementById('lib-fb');
      const newBackend  = e.target.value;
      const prevBackend = this._backend;

      try {
        const resp = await fetch('/api/fraimic/library/settings', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ backend: newBackend }),
        });
        const result = await resp.json().catch(() => ({}));

        if (resp.ok && result.success) {
          this._backend = newBackend;
          fb.className = 'feedback ok';
          fb.textContent = `✓ Storage set to ${newBackend.replace('_', ' ')}`;
        } else {
          e.target.value = prevBackend;
          fb.className = 'feedback err';
          fb.textContent = result.message || resp.statusText || `HTTP ${resp.status}`;
        }
      } catch (err) {
        e.target.value = prevBackend;
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 5000);
    }

    // -----------------------------------------------------------------------
    // Library: list + render
    // -----------------------------------------------------------------------

    async _loadLibrary() {
      try {
        const resp = await fetch('/api/fraimic/library/list', { headers: this._authHeaders() });
        const result = await resp.json();
        this._library = result.images || [];
        if (result.backend) this._backend = result.backend;
      } catch (err) {
        console.error('[fraimic-panel] library load failed:', err);
        this._library = [];
      }
    }

    _renderLibrary() {
      const grid = this.shadowRoot.getElementById('lib-grid');

      // Release previously-fetched thumbnail blob URLs before re-rendering.
      for (const url of Object.values(this._libThumbUrls)) URL.revokeObjectURL(url);
      this._libThumbUrls = {};

      if (!this._library.length) {
        grid.innerHTML = `
          <div class="empty">
            <div style="font-size:48px">📚</div>
            <h2>Library is empty</h2>
            <p>Upload an image above to add it to the shared library. It's converted
               once per frame resolution and reused by every frame that matches —
               no need to re-upload per frame.</p>
          </div>
        `;
        return;
      }

      grid.innerHTML = '';
      for (const image of this._library) {
        grid.appendChild(this._buildLibraryCard(image));
      }
    }

    _buildLibraryCard(image) {
      const el  = document.createElement('div');
      el.className = 'card lib-card';
      const sid = this._sid(image.image_id);

      const frameOptions = this._frames.map(f =>
        `<option value="${this._esc(f.entityId)}">${this._esc(f.title)}</option>`
      ).join('');

      el.innerHTML = `
        <div class="lib-thumb" id="thumb-${sid}">
          <div style="font-size:32px;text-align:center;padding:30px 0">🖼</div>
        </div>
        <div class="preview-name">${this._esc(image.filename)}</div>
        <div class="btns" style="margin-top:10px">
          <select id="frame-select-${sid}" ${this._frames.length ? '' : 'disabled'}>
            ${frameOptions || '<option>No frames available</option>'}
          </select>
          <button class="btn-primary" id="lib-send-${sid}" ${this._frames.length ? '' : 'disabled'}>⬆ Send</button>
          <button class="btn-ghost" id="lib-delete-${sid}" title="Remove from library">🗑</button>
        </div>
        <div class="feedback" id="lib-card-fb-${sid}"></div>
      `;

      this._loadThumbnail(image.image_id, el.querySelector(`#thumb-${sid}`));

      el.querySelector(`#lib-send-${sid}`).addEventListener('click', () => {
        const entityId = el.querySelector(`#frame-select-${sid}`).value;
        if (entityId) this._sendFromLibrary(image.image_id, entityId, el, sid);
      });

      el.querySelector(`#lib-delete-${sid}`).addEventListener('click', () => {
        this._deleteFromLibrary(image.image_id);
      });

      return el;
    }

    async _loadThumbnail(imageId, container) {
      try {
        const resp = await fetch(`/api/fraimic/library/image/${imageId}`, { headers: this._authHeaders() });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        this._libThumbUrls[imageId] = url;
        container.innerHTML = `<img src="${url}" alt="">`;
      } catch (err) {
        console.warn('[fraimic-panel] thumbnail load failed:', err);
      }
    }

    // -----------------------------------------------------------------------
    // Library: delete
    // -----------------------------------------------------------------------

    async _deleteFromLibrary(imageId) {
      const fb = this.shadowRoot.getElementById('lib-fb');
      try {
        const resp = await fetch(`/api/fraimic/library/image/${imageId}`, {
          method: 'DELETE', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (resp.ok && result.success) {
          await this._loadLibrary();
          this._renderLibrary();
        } else {
          fb.className = 'feedback err';
          fb.textContent = `Delete failed: ${result.message || resp.statusText || resp.status}`;
          fb.style.display = 'block';
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    // -----------------------------------------------------------------------
    // Library: upload
    // -----------------------------------------------------------------------

    async _onLibraryFile(file) {
      const fb = this.shadowRoot.getElementById('lib-fb');
      fb.style.display = 'none';

      const form = new FormData();
      form.append('image', file);

      try {
        const resp = await fetch('/api/fraimic/library/upload', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));

        if (resp.ok && result.success) {
          fb.className = 'feedback ok';
          fb.textContent = '✓ Added to library';
          await this._loadLibrary();
          this._renderLibrary();
        } else {
          fb.className = 'feedback err';
          fb.textContent = `Upload failed: ${result.message || resp.statusText || resp.status}`;
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
      this.shadowRoot.getElementById('lib-upload-input').value = '';
    }

    // -----------------------------------------------------------------------
    // Library: send to frame
    // -----------------------------------------------------------------------

    async _sendFromLibrary(imageId, entityId, el, sid) {
      const btn = el.querySelector(`#lib-send-${sid}`);
      const fb  = el.querySelector(`#lib-card-fb-${sid}`);
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Sending…';

      const form = new FormData();
      form.append('entity_id', entityId);
      form.append('image_id', imageId);

      try {
        const resp = await fetch('/api/fraimic/library/send', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));

        if (resp.ok && result.success) {
          fb.className = 'feedback ok';
          fb.textContent = '✓ Sent!';
        } else {
          fb.className = 'feedback err';
          fb.textContent = `Failed: ${result.message || resp.statusText || resp.status}`;
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';

      btn.disabled = false;
      btn.textContent = prevText;
      setTimeout(() => { fb.style.display = 'none'; }, 4000);
    }

    // -----------------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------------

    _authHeaders() {
      let token;
      try { token = this._hass.auth.data.access_token; } catch (_) {}
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

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
