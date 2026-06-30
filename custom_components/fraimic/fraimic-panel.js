/**
 * Fraimic Panel
 * Sidebar panel that auto-discovers all Fraimic frames and lets you send
 * images to any of them — no manual card configuration required.
 */

(function () {
  'use strict';

  const PANEL_VERSION = '0.4.0';

  // Mirrors const.py's FRAME_RESOLUTIONS -- real hardware pixel counts for
  // each physical panel size, in their native (un-rotated) orientation.
  const FRAME_SIZES = {
    '13.3': { width: 1200, height: 1600 }, // portrait-native
    '31.5': { width: 2560, height: 1440 }, // landscape-native
  };

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
    .card.deep-link-highlight {
      outline: 3px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
      transition: outline-color 0.3s ease;
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
    .backend-config {
      margin: 4px 0 16px;
    }
    .backend-form {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .backend-form input[type="text"], .backend-form input[type="password"] {
      flex: 1;
      min-width: 180px;
      padding: 7px 10px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, rgba(0,0,0,.15));
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-size: 13px;
    }
    .muted {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin: 6px 0 0;
      line-height: 1.5;
    }
    .muted code {
      background: var(--secondary-background-color, #f1f5f9);
      padding: 2px 5px;
      border-radius: 4px;
      font-size: 11px;
      word-break: break-all;
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
    .lib-thumb { cursor: pointer; }

    /* -- crop / size / orientation editor -------------------------------- */
    .editor-overlay {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, .85);
      z-index: 1000;
      display: none;
      flex-direction: column;
      color: #fff;
    }
    .editor-header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 18px;
      flex: 0 0 auto;
    }
    .editor-back {
      flex: 0 0 auto;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: rgba(255,255,255,.12);
      color: #fff;
      border: none;
      font-size: 18px;
      cursor: pointer;
    }
    .editor-title {
      font-size: 14px;
      font-weight: 500;
      opacity: .9;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .editor-stage {
      flex: 1 1 auto;
      position: relative;
      margin: 0 18px;
      min-height: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .editor-stage img {
      max-width: 100%;
      max-height: 100%;
      display: block;
      user-select: none;
      -webkit-user-drag: none;
    }
    .crop-box {
      position: absolute;
      border: 2px solid #f97316;
      box-shadow: 0 0 0 4000px rgba(0,0,0,.45);
      touch-action: none;
      cursor: move;
    }
    .crop-handle {
      position: absolute;
      width: 16px;
      height: 16px;
      background: #f97316;
      border: 2px solid #fff;
      border-radius: 50%;
      touch-action: none;
    }
    .crop-handle.tl { left: -9px; top: -9px; cursor: nwse-resize; }
    .crop-handle.tr { right: -9px; top: -9px; cursor: nesw-resize; }
    .crop-handle.bl { left: -9px; bottom: -9px; cursor: nesw-resize; }
    .crop-handle.br { right: -9px; bottom: -9px; cursor: nwse-resize; }
    .editor-controls {
      flex: 0 0 auto;
      padding: 16px 18px 22px;
      max-width: 420px;
      margin: 0 auto;
      width: 100%;
      box-sizing: border-box;
    }
    .editor-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
      gap: 12px;
    }
    .editor-label {
      font-size: 13px;
      opacity: .8;
      flex: 0 0 auto;
    }
    .pill-group { display: flex; gap: 8px; }
    .pill {
      padding: 7px 16px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.3);
      background: transparent;
      color: #fff;
      font-size: 13px;
      cursor: pointer;
      flex: 0 0 auto;
    }
    .pill.active {
      background: #f97316;
      border-color: #f97316;
      font-weight: 600;
    }
    #editor-frame-row select {
      flex: 1;
      padding: 7px 10px;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,.3);
      background: rgba(255,255,255,.08);
      color: #fff;
      font-size: 13px;
    }
    .editor-actions {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 6px;
    }
    .editor-actions button {
      width: 100%;
      padding: 12px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid rgba(255,255,255,.25);
      background: transparent;
      color: #fff;
    }
    .editor-actions .btn-primary { background: #f97316; border-color: #f97316; color: #fff; }
    .editor-actions .editor-danger { color: #f87171; border-color: rgba(248,113,113,.4); }
    #editor-fb { margin-top: 10px; }
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

      this._editorState = null;   // active crop-editor session, or null when closed
      this._editorDrag  = null;   // in-progress pointer drag, or null
      this._editorImgUrl = null;  // blob: URL for the editor's full-size image
      this._onEditorPointerMove = this._onEditorPointerMove.bind(this);
      this._onEditorPointerUp   = this._onEditorPointerUp.bind(this);
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
      this._wireEditor();
      await this._discoverFrames();
      this._renderFrames();
      this._handleDeepLink();
      await this._loadBackendSettings();
      await this._loadLibrary();
      this._renderLibrary();
    }

    // Coming from a device page's "Visit" link (/fraimic?entry=<entry_id>):
    // jump straight to that frame's card and pop its upload dialog open.
    _handleDeepLink() {
      let entryId;
      try {
        entryId = new URLSearchParams(window.location.search).get('entry');
      } catch (err) {
        return;
      }
      if (!entryId) return;

      const frame = this._frames.find(f => f.entryId === entryId);
      if (!frame) return;
      const card = this._cards[frame.entityId];
      if (!card) return;

      card.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.el.classList.add('deep-link-highlight');
      setTimeout(() => card.el.classList.remove('deep-link-highlight'), 3000);

      const sid = this._sid(frame.entityId);
      const fileInput = this.shadowRoot.getElementById(`file-${sid}`);
      if (fileInput) fileInput.click();
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
        <div class="backend-config" id="backend-config"></div>
        <div class="feedback" id="lib-fb"></div>
        <div class="lib-grid" id="lib-grid">
          <div class="empty">
            <div style="font-size:36px">⏳</div>
            <h2>Loading library…</h2>
          </div>
        </div>

        <div class="editor-overlay" id="editor-overlay">
          <div class="editor-header">
            <button class="editor-back" id="editor-back" title="Cancel">←</button>
            <div class="editor-title" id="editor-title"></div>
          </div>
          <div class="editor-stage" id="editor-stage">
            <img id="editor-img" alt="">
            <div class="crop-box" id="editor-cropbox">
              <div class="crop-handle tl" data-handle="tl"></div>
              <div class="crop-handle tr" data-handle="tr"></div>
              <div class="crop-handle bl" data-handle="bl"></div>
              <div class="crop-handle br" data-handle="br"></div>
            </div>
          </div>
          <div class="editor-controls">
            <div class="editor-row">
              <span class="editor-label">Frame size</span>
              <div class="pill-group" id="editor-size-group">
                <button class="pill" data-size="13.3">13.3"</button>
                <button class="pill" data-size="31.5">31.5"</button>
              </div>
            </div>
            <div class="editor-row">
              <span class="editor-label">Orientation</span>
              <div class="pill-group" id="editor-orientation-group">
                <button class="pill" data-orientation="portrait">Portrait</button>
                <button class="pill" data-orientation="landscape">Landscape</button>
              </div>
            </div>
            <div class="editor-row" id="editor-frame-row">
              <span class="editor-label">Send to</span>
              <select id="editor-frame-select"></select>
            </div>
            <div class="editor-actions">
              <button class="btn-primary" id="editor-send">⬆ Send to Canvas</button>
              <button class="btn-ghost" id="editor-add-album">＋ Add to Album</button>
              <button class="btn-ghost" id="editor-reset">↺ Reset crop</button>
              <button class="btn-ghost editor-danger" id="editor-delete">🗑 Delete</button>
              <button class="btn-ghost" id="editor-cancel">Cancel</button>
            </div>
            <div class="feedback" id="editor-fb"></div>
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
            entryId:  entry.entry_id,
          };
        }).filter(f => f.entityId); // only frames we can identify
      } catch (err) {
        console.error('[fraimic-panel] discovery failed:', err);
        this._frames = [];
      }

      // The WS APIs above never expose entry.data (it's redacted), so a frame's
      // configured resolution has to come from our own backend endpoint instead.
      // Used by the Library crop editor to filter "Send to" by matching size.
      try {
        const resp = await fetch('/api/fraimic/frames', { headers: this._authHeaders() });
        if (resp.ok) {
          const result = await resp.json();
          const byEntry = {};
          for (const f of (result.frames || [])) byEntry[f.entry_id] = f;
          for (const frame of this._frames) {
            const match = byEntry[frame.entryId];
            if (match) { frame.width = match.width; frame.height = match.height; }
          }
        }
      } catch (err) {
        console.warn('[fraimic-panel] frame resolution lookup failed:', err);
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

      backendSelect.addEventListener('change', e => this._renderBackendConfig(e.target.value));
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
      this._renderBackendConfig(this._backend);
    }

    _renderBackendConfig(selected) {
      const container = this.shadowRoot.getElementById('backend-config');
      if (!container) return;

      if (selected === 'local') {
        container.innerHTML = (this._backend === 'local')
          ? `<p class="muted">✓ Using local storage on this Home Assistant.</p>`
          : `<button class="btn-primary" id="backend-use-local" style="flex:0 0 auto">Use Local Storage</button>`;
        const btn = container.querySelector('#backend-use-local');
        if (btn) btn.addEventListener('click', () => this._switchBackend({ backend: 'local' }));
        return;
      }

      if (selected === 'dropbox') {
        if (this._backend === 'dropbox') {
          container.innerHTML = `<p class="muted">✓ Connected to Dropbox.</p>`;
          return;
        }
        container.innerHTML = `
          <div class="backend-form">
            <input type="password" id="dropbox-token" placeholder="Dropbox access token">
            <button class="btn-primary" id="dropbox-connect" style="flex:0 0 auto">Save &amp; Connect</button>
          </div>
          <p class="muted">Dropbox App Console → your app → Permissions tab → "Generated access token". Paste it here.</p>
        `;
        container.querySelector('#dropbox-connect').addEventListener('click', () => {
          const token = container.querySelector('#dropbox-token').value.trim();
          if (!token) return;
          this._switchBackend({ backend: 'dropbox', access_token: token });
        });
        return;
      }

      if (selected === 'google_drive') {
        if (this._backend === 'google_drive') {
          container.innerHTML = `<p class="muted">✓ Connected to Google Drive.</p>`;
          return;
        }
        container.innerHTML = `
          <div class="backend-form">
            <input type="text" id="gdrive-client-id" placeholder="OAuth Client ID">
            <input type="password" id="gdrive-client-secret" placeholder="OAuth Client Secret">
            <button class="btn-primary" id="gdrive-connect" style="flex:0 0 auto">Connect Google Drive</button>
          </div>
          <p class="muted" id="gdrive-hint">Loading redirect URI…</p>
        `;
        this._loadGoogleRedirectUri();
        container.querySelector('#gdrive-connect').addEventListener('click', () => this._connectGoogleDrive());
      }
    }

    async _loadGoogleRedirectUri() {
      const hint = this.shadowRoot.getElementById('gdrive-hint');
      if (!hint) return;
      try {
        const resp = await fetch('/api/fraimic/library/oauth/google/redirect_uri', { headers: this._authHeaders() });
        const result = await resp.json();
        if (result.redirect_uri) {
          hint.innerHTML = `In Google Cloud Console, create an OAuth Client ID (type: Web application) `
            + `and add this as an Authorized redirect URI, then enable the Google Drive API:<br>`
            + `<code>${this._esc(result.redirect_uri)}</code>`;
        } else {
          hint.textContent = 'Set an External URL under Settings → System → Network in Home Assistant first — Google needs a stable redirect URL.';
        }
      } catch (err) {
        hint.textContent = `Could not determine redirect URI: ${err.message}`;
      }
    }

    async _connectGoogleDrive() {
      const fb = this.shadowRoot.getElementById('lib-fb');
      const clientId     = this.shadowRoot.getElementById('gdrive-client-id').value.trim();
      const clientSecret = this.shadowRoot.getElementById('gdrive-client-secret').value.trim();
      if (!clientId || !clientSecret) return;

      try {
        const resp = await fetch('/api/fraimic/library/oauth/google/start', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
        });
        const result = await resp.json().catch(() => ({}));
        if (resp.ok && result.auth_url) {
          window.open(result.auth_url, '_blank');
          fb.className = 'feedback ok';
          fb.textContent = 'Complete the Google sign-in in the new tab, then come back here and refresh.';
        } else {
          fb.className = 'feedback err';
          fb.textContent = result.message || 'Could not start Google authorization.';
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 8000);
    }

    async _switchBackend(settings) {
      const fb = this.shadowRoot.getElementById('lib-fb');
      try {
        const resp = await fetch('/api/fraimic/library/settings', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify(settings),
        });
        const result = await resp.json().catch(() => ({}));

        if (resp.ok && result.success) {
          this._backend = result.backend;
          fb.className = 'feedback ok';
          fb.textContent = `✓ Storage set to ${result.backend.replace('_', ' ')}`;
          const sel = this.shadowRoot.getElementById('backend-select');
          this._renderBackendConfig(sel ? sel.value : this._backend);
          await this._loadLibrary();
          this._renderLibrary();
        } else {
          fb.className = 'feedback err';
          fb.textContent = result.message || resp.statusText || `HTTP ${resp.status}`;
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 6000);
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

      el.querySelector(`#thumb-${sid}`).addEventListener('click', () => {
        this._openEditor(image);
      });

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
    // Library: crop / size / orientation editor
    // -----------------------------------------------------------------------

    // Given a frame size key ('13.3' / '31.5') and an orientation
    // ('portrait' / 'landscape'), return the target pixel dimensions to
    // render at. The crop box's aspect ratio alone encodes the orientation
    // choice -- the source image is never rotated, only the crop shape changes.
    _editorTargetDims(sizeKey, orientation) {
      const native = FRAME_SIZES[sizeKey];
      const isNativePortrait = native.height >= native.width;
      const wantPortrait = orientation === 'portrait';
      if (isNativePortrait === wantPortrait) {
        return { width: native.width, height: native.height };
      }
      return { width: native.height, height: native.width };
    }

    // Centered crop rectangle (normalized x0,y0,x1,y1) matching targetW:targetH,
    // as large as the original image allows, optionally re-centered on a
    // given point so switching size/orientation doesn't jump wildly.
    _editorComputeCoverBox(naturalW, naturalH, targetW, targetH, centerX = 0.5, centerY = 0.5) {
      const ar = targetW / targetH;
      const origAr = naturalW / naturalH;
      let cropWFrac, cropHFrac;
      if (origAr > ar) {
        cropHFrac = 1;
        cropWFrac = (naturalH * ar) / naturalW;
      } else {
        cropWFrac = 1;
        cropHFrac = (naturalW / ar) / naturalH;
      }
      let x0 = centerX - cropWFrac / 2;
      let y0 = centerY - cropHFrac / 2;
      x0 = Math.min(Math.max(x0, 0), 1 - cropWFrac);
      y0 = Math.min(Math.max(y0, 0), 1 - cropHFrac);
      return [x0, y0, x0 + cropWFrac, y0 + cropHFrac];
    }

    // Attach the editor's static (one-time) event listeners. Called once
    // from _init() right after _buildShell() creates the overlay markup.
    _wireEditor() {
      const root = this.shadowRoot;
      root.getElementById('editor-back').addEventListener('click', () => this._closeEditor());
      root.getElementById('editor-cancel').addEventListener('click', () => this._closeEditor());
      root.getElementById('editor-reset').addEventListener('click', () => this._editorResetCrop());
      root.getElementById('editor-add-album').addEventListener('click', () => this._editorAddToAlbum());
      root.getElementById('editor-send').addEventListener('click', () => this._editorSendToCanvas());
      root.getElementById('editor-delete').addEventListener('click', () => this._editorDeleteImage());

      root.querySelectorAll('#editor-size-group .pill').forEach(btn => {
        btn.addEventListener('click', () => {
          this._editorSetSizeOrientation(btn.dataset.size, this._editorState.orientation);
        });
      });
      root.querySelectorAll('#editor-orientation-group .pill').forEach(btn => {
        btn.addEventListener('click', () => {
          this._editorSetSizeOrientation(this._editorState.sizeKey, btn.dataset.orientation);
        });
      });

      const cropEl = root.getElementById('editor-cropbox');
      cropEl.addEventListener('pointerdown', (e) => {
        if (e.target.classList.contains('crop-handle')) return;
        this._editorBeginDrag(e, 'move', null);
      });
      cropEl.querySelectorAll('.crop-handle').forEach(handle => {
        handle.addEventListener('pointerdown', (e) => {
          this._editorBeginDrag(e, 'resize', handle.dataset.handle);
        });
      });
    }

    // Open the editor for a library image. Picks whichever Frame
    // size/orientation combo already has a saved crop (if any), loads the
    // full image, then renders.
    async _openEditor(image) {
      this._editorState = {
        image,
        sizeKey: '13.3',
        orientation: 'portrait',
        targetWidth: 0,
        targetHeight: 0,
        naturalW: 0,
        naturalH: 0,
        cropBox: null,
        cropIsSaved: false,
      };

      outer:
      for (const sizeKey of Object.keys(FRAME_SIZES)) {
        for (const orientation of ['portrait', 'landscape']) {
          const dims = this._editorTargetDims(sizeKey, orientation);
          const key = `${dims.width}x${dims.height}`;
          if (image.crops && image.crops[key]) {
            this._editorState.sizeKey = sizeKey;
            this._editorState.orientation = orientation;
            break outer;
          }
        }
      }

      const overlay = this.shadowRoot.getElementById('editor-overlay');
      overlay.style.display = 'flex';
      this.shadowRoot.getElementById('editor-title').textContent = image.filename;

      const img = this.shadowRoot.getElementById('editor-img');
      img.removeAttribute('src');

      try {
        const resp = await fetch(`/api/fraimic/library/image/${image.image_id}`, { headers: this._authHeaders() });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        if (this._editorImgUrl) URL.revokeObjectURL(this._editorImgUrl);
        this._editorImgUrl = URL.createObjectURL(blob);
        img.src = this._editorImgUrl;
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = () => reject(new Error('image decode failed'));
        });
        this._editorState.naturalW = img.naturalWidth;
        this._editorState.naturalH = img.naturalHeight;
      } catch (err) {
        this._editorShowFb('err', `Couldn't load image: ${err.message}`);
        return;
      }

      this._editorSetSizeOrientation(this._editorState.sizeKey, this._editorState.orientation);
    }

    _closeEditor() {
      const overlay = this.shadowRoot.getElementById('editor-overlay');
      overlay.style.display = 'none';
      if (this._editorImgUrl) {
        URL.revokeObjectURL(this._editorImgUrl);
        this._editorImgUrl = null;
      }
      this._editorDrag = null;
      this._editorState = null;
    }

    // Switch the Frame size and/or Orientation pill selection: recomputes
    // the target render dimensions, loads any crop already saved for that
    // exact resolution, or otherwise falls back to a centered cover-crop
    // (re-centered on wherever the previous box was looking, so switching
    // orientation doesn't make the crop jump to a random spot).
    _editorSetSizeOrientation(sizeKey, orientation) {
      const st = this._editorState;
      st.sizeKey = sizeKey;
      st.orientation = orientation;
      const dims = this._editorTargetDims(sizeKey, orientation);
      st.targetWidth = dims.width;
      st.targetHeight = dims.height;

      const key = `${dims.width}x${dims.height}`;
      const saved = st.image.crops && st.image.crops[key];
      if (saved) {
        st.cropBox = saved.slice();
        st.cropIsSaved = true;
      } else {
        let cx = 0.5, cy = 0.5;
        if (st.cropBox) {
          cx = (st.cropBox[0] + st.cropBox[2]) / 2;
          cy = (st.cropBox[1] + st.cropBox[3]) / 2;
        }
        st.cropBox = this._editorComputeCoverBox(st.naturalW, st.naturalH, dims.width, dims.height, cx, cy);
        st.cropIsSaved = false;
      }

      this._editorUpdatePills();
      this._editorUpdateFrameSelect();
      this._editorRenderCropBox();
    }

    _editorUpdatePills() {
      const st = this._editorState;
      this.shadowRoot.querySelectorAll('#editor-size-group .pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.size === st.sizeKey);
      });
      this.shadowRoot.querySelectorAll('#editor-orientation-group .pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.orientation === st.orientation);
      });
    }

    // Only frames configured at exactly the current target resolution can
    // receive this crop -- a different resolution would mean a different
    // crop math, so the "Send to" list is filtered rather than showing
    // every frame like the quick per-frame picker does.
    _editorUpdateFrameSelect() {
      const st = this._editorState;
      const select = this.shadowRoot.getElementById('editor-frame-select');
      const sendBtn = this.shadowRoot.getElementById('editor-send');
      const matches = this._frames.filter(f => f.width === st.targetWidth && f.height === st.targetHeight);

      if (!matches.length) {
        select.innerHTML = '<option value="">No matching frame configured</option>';
        select.disabled = true;
        sendBtn.disabled = true;
        return;
      }
      select.disabled = false;
      sendBtn.disabled = false;
      select.innerHTML = matches.map(f =>
        `<option value="${this._esc(f.entityId)}">${this._esc(f.title)}</option>`
      ).join('');
    }

    // The on-screen rect (in editor-stage-local pixels) that the image is
    // actually rendered into -- accounts for the letterboxing object-fit:
    // contain introduces when the image's aspect ratio differs from the
    // stage's.
    _editorImageRect() {
      const stage = this.shadowRoot.getElementById('editor-stage');
      const stageW = stage.clientWidth;
      const stageH = stage.clientHeight;
      const { naturalW, naturalH } = this._editorState;
      if (!naturalW || !naturalH) {
        return { offsetX: 0, offsetY: 0, renderedW: stageW, renderedH: stageH };
      }
      const scale = Math.min(stageW / naturalW, stageH / naturalH);
      const renderedW = naturalW * scale;
      const renderedH = naturalH * scale;
      return {
        offsetX: (stageW - renderedW) / 2,
        offsetY: (stageH - renderedH) / 2,
        renderedW,
        renderedH,
      };
    }

    _editorRenderCropBox() {
      const box = this._editorState && this._editorState.cropBox;
      if (!box) return;
      const { offsetX, offsetY, renderedW, renderedH } = this._editorImageRect();
      const el = this.shadowRoot.getElementById('editor-cropbox');
      el.style.left   = `${offsetX + box[0] * renderedW}px`;
      el.style.top    = `${offsetY + box[1] * renderedH}px`;
      el.style.width  = `${(box[2] - box[0]) * renderedW}px`;
      el.style.height = `${(box[3] - box[1]) * renderedH}px`;
    }

    _editorBeginDrag(e, mode, handle) {
      e.preventDefault();
      e.stopPropagation();
      this._editorDrag = {
        mode,
        handle,
        startClientX: e.clientX,
        startClientY: e.clientY,
        startBox: this._editorState.cropBox.slice(),
        imgRect: this._editorImageRect(),
      };
      window.addEventListener('pointermove', this._onEditorPointerMove);
      window.addEventListener('pointerup', this._onEditorPointerUp);
    }

    _onEditorPointerMove(e) {
      const drag = this._editorDrag;
      if (!drag) return;
      const { renderedW, renderedH } = drag.imgRect;
      const dxNorm = (e.clientX - drag.startClientX) / renderedW;
      const dyNorm = (e.clientY - drag.startClientY) / renderedH;
      const [sx0, sy0, sx1, sy1] = drag.startBox;

      let box;
      if (drag.mode === 'move') {
        const w = sx1 - sx0, h = sy1 - sy0;
        let x0 = Math.min(Math.max(sx0 + dxNorm, 0), 1 - w);
        let y0 = Math.min(Math.max(sy0 + dyNorm, 0), 1 - h);
        box = [x0, y0, x0 + w, y0 + h];
      } else {
        const ar = this._editorState.targetWidth / this._editorState.targetHeight;
        box = this._editorResizeBox(drag.startBox, drag.handle, dxNorm, dyNorm, ar);
      }

      this._editorState.cropBox = box;
      this._editorRenderCropBox();
    }

    _onEditorPointerUp() {
      this._editorDrag = null;
      window.removeEventListener('pointermove', this._onEditorPointerMove);
      window.removeEventListener('pointerup', this._onEditorPointerUp);
      if (this._editorState) this._editorState.cropIsSaved = false;
    }

    // AR-locked resize: the corner opposite the dragged handle stays fixed
    // (the "anchor"); the dragged corner's distance from the anchor sets the
    // box size along whichever axis moved further, with the other axis
    // derived from the target aspect ratio. Clamped to stay inside [0,1].
    _editorResizeBox(startBox, handle, dxNorm, dyNorm, ar) {
      const [sx0, sy0, sx1, sy1] = startBox;
      const anchors = { tl: [sx1, sy1], tr: [sx0, sy1], bl: [sx1, sy0], br: [sx0, sy0] };
      const corners = { tl: [sx0, sy0], tr: [sx1, sy0], bl: [sx0, sy1], br: [sx1, sy1] };
      const [ax, ay] = anchors[handle];
      const [fx0, fy0] = corners[handle];
      const fx = fx0 + dxNorm;
      const fy = fy0 + dyNorm;

      let w = Math.abs(fx - ax);
      let h = Math.abs(fy - ay);
      if (h * ar > w) {
        w = h * ar;
      } else {
        h = w / ar;
      }
      const minW = 0.05;
      if (w < minW) { w = minW; h = w / ar; }

      const dirX = fx >= ax ? 1 : -1;
      const dirY = fy >= ay ? 1 : -1;
      let x0 = dirX > 0 ? ax : ax - w;
      let x1 = dirX > 0 ? ax + w : ax;
      let y0 = dirY > 0 ? ay : ay - h;
      let y1 = dirY > 0 ? ay + h : ay;

      if (x0 < 0) { x0 = 0; x1 = Math.min(x0 + w, 1); }
      if (x1 > 1) { x1 = 1; x0 = Math.max(x1 - w, 0); }
      if (y0 < 0) { y0 = 0; y1 = Math.min(y0 + h, 1); }
      if (y1 > 1) { y1 = 1; y0 = Math.max(y1 - h, 0); }
      if (x1 - x0 > 1) { x0 = 0; x1 = 1; }
      if (y1 - y0 > 1) { y0 = 0; y1 = 1; }

      return [x0, y0, x1, y1];
    }

    async _editorSaveCrop() {
      const st = this._editorState;
      const resp = await fetch('/api/fraimic/library/crop', {
        method: 'POST',
        headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_id: st.image.image_id,
          width: st.targetWidth,
          height: st.targetHeight,
          crop_box: st.cropBox,
        }),
      });
      const result = await resp.json().catch(() => ({}));
      if (!resp.ok || !result.success) {
        throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
      }
      st.image.crops = result.image.crops;
      st.cropIsSaved = true;
      const libImg = this._library.find(i => i.image_id === st.image.image_id);
      if (libImg) libImg.crops = result.image.crops;
    }

    // Reverts to the original (uncropped/letterboxed) framing for the
    // current size+orientation -- distinct from Cancel, which just discards
    // unsaved in-editor changes without touching what's persisted.
    async _editorResetCrop() {
      const st = this._editorState;
      try {
        const resp = await fetch('/api/fraimic/library/crop', {
          method: 'DELETE',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_id: st.image.image_id, width: st.targetWidth, height: st.targetHeight }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        st.image.crops = result.image.crops;
        const libImg = this._library.find(i => i.image_id === st.image.image_id);
        if (libImg) libImg.crops = result.image.crops;

        st.cropBox = this._editorComputeCoverBox(st.naturalW, st.naturalH, st.targetWidth, st.targetHeight);
        st.cropIsSaved = false;
        this._editorRenderCropBox();
        this._editorShowFb('ok', 'Reverted to the original framing for this size.');
      } catch (err) {
        this._editorShowFb('err', `Couldn't reset crop: ${err.message}`);
      }
    }

    async _editorAddToAlbum() {
      try {
        await this._editorSaveCrop();
        this._editorShowFb('ok', '✓ Crop saved');
        setTimeout(() => this._closeEditor(), 700);
      } catch (err) {
        this._editorShowFb('err', `Couldn't save crop: ${err.message}`);
      }
    }

    async _editorSendToCanvas() {
      const st = this._editorState;
      const select = this.shadowRoot.getElementById('editor-frame-select');
      const entityId = select && select.value;
      if (!entityId) {
        this._editorShowFb('err', 'No frame configured for this size/orientation yet.');
        return;
      }

      const btn = this.shadowRoot.getElementById('editor-send');
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Sending…';

      try {
        await this._editorSaveCrop();
        const form = new FormData();
        form.append('entity_id', entityId);
        form.append('image_id', st.image.image_id);
        const resp = await fetch('/api/fraimic/library/send', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        this._editorShowFb('ok', '✓ Sent!');
        setTimeout(() => this._closeEditor(), 1200);
      } catch (err) {
        this._editorShowFb('err', `Failed: ${err.message}`);
      }

      btn.disabled = false;
      btn.textContent = prevText;
    }

    async _editorDeleteImage() {
      const st = this._editorState;
      if (!window.confirm(`Delete "${st.image.filename}" from the library? This can't be undone.`)) return;
      await this._deleteFromLibrary(st.image.image_id);
      this._closeEditor();
    }

    _editorShowFb(type, msg) {
      const fb = this.shadowRoot.getElementById('editor-fb');
      fb.className = `feedback ${type}`;
      fb.textContent = msg;
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 5000);
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
