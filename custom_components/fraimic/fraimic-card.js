/**
 * Fraimic Frame Card
 * Custom Lovelace card for sending images to a Fraimic e-ink frame.
 *
 * Config:
 *   type: custom:fraimic-card
 *   entity: sensor.frame_1_battery   # any Fraimic sensor for this frame
 *   name: Frame 1                    # optional friendly name override
 */

(function () {
  'use strict';

  const CARD_VERSION = '0.1.4';

  class FraimicCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._selectedFile = null;
      this._previewUrl = null;
    }

    // ------------------------------------------------------------------ //
    // Lovelace card protocol
    // ------------------------------------------------------------------ //

    static getStubConfig() {
      return { entity: 'sensor.frame_1_battery' };
    }

    setConfig(config) {
      if (!config.entity) {
        throw new Error(
          'fraimic-card: please set entity to a Fraimic sensor ' +
          '(e.g. sensor.frame_1_battery)'
        );
      }
      this._config = config;
      this._build();
    }

    set hass(hass) {
      this._hass = hass;
      this._refreshStatus();
    }

    // ------------------------------------------------------------------ //
    // DOM construction (called once from setConfig)
    // ------------------------------------------------------------------ //

    _build() {
      this.shadowRoot.innerHTML = `
        <style>
          *, *::before, *::after { box-sizing: border-box; }

          ha-card {
            padding: 16px 16px 12px;
            overflow: hidden;
          }

          /* ---- header ---- */
          .header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 14px;
          }
          .icon {
            width: 42px; height: 42px;
            border-radius: 10px;
            background: var(--primary-color, #03a9f4);
            display: flex; align-items: center; justify-content: center;
            font-size: 22px;
            flex-shrink: 0;
          }
          .meta { flex: 1; min-width: 0; }
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
            margin-top: 2px;
          }
          .dot-online  { color: var(--success-color,  #43a047); }
          .dot-offline { color: var(--error-color,    #e53935); }

          /* ---- preview ---- */
          .preview {
            display: none;
            margin-bottom: 12px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--divider-color, rgba(0,0,0,.12));
            background: var(--secondary-background-color, #f5f5f5);
            text-align: center;
          }
          .preview img {
            display: block;
            width: 100%;
            max-height: 220px;
            object-fit: contain;
          }
          .preview-caption {
            padding: 4px 8px;
            font-size: 11px;
            color: var(--secondary-text-color);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          /* ---- buttons ---- */
          .actions { display: flex; gap: 8px; }

          button {
            flex: 1;
            padding: 9px 12px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: opacity .15s, transform .1s;
            line-height: 1.2;
          }
          button:active:not(:disabled) { transform: scale(.97); }
          button:disabled { opacity: .45; cursor: default; }

          .btn-pick {
            background: var(--primary-color, #03a9f4);
            color: var(--text-primary-color, #fff);
          }
          .btn-send {
            background: var(--primary-color, #03a9f4);
            color: var(--text-primary-color, #fff);
            display: none;
          }
          .btn-cancel {
            background: var(--secondary-background-color, #eee);
            color: var(--primary-text-color);
            display: none;
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
          .feedback.success {
            background: rgba(67,160,71,.12);
            color: var(--success-color, #2e7d32);
          }
          .feedback.error {
            background: rgba(229,57,53,.10);
            color: var(--error-color, #c62828);
          }

          input[type="file"] { display: none; }
        </style>

        <ha-card>
          <div class="card-content">

            <div class="header">
              <div class="icon">🖼</div>
              <div class="meta">
                <div class="frame-name" id="frameName">Fraimic Frame</div>
                <div class="frame-status" id="frameStatus"></div>
              </div>
            </div>

            <div class="preview" id="preview">
              <img id="previewImg" alt="Preview" />
              <div class="preview-caption" id="previewCaption"></div>
            </div>

            <div class="actions">
              <button class="btn-pick" id="btnPick">📷 Send Image</button>
              <button class="btn-send" id="btnSend">⬆ Send to Frame</button>
              <button class="btn-cancel" id="btnCancel">✕</button>
            </div>

            <div class="feedback" id="feedback"></div>

            <input type="file" id="fileInput"
              accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/*">
          </div>
        </ha-card>
      `;

      // Wire up events.
      this._q('btnPick').addEventListener('click', () => {
        this._q('fileInput').click();
      });

      this._q('fileInput').addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) this._onFileSelected(file);
      });

      this._q('btnSend').addEventListener('click', () => this._sendImage());
      this._q('btnCancel').addEventListener('click', () => this._reset());

      // Populate status immediately if hass is already set.
      if (this._hass) this._refreshStatus();
    }

    // ------------------------------------------------------------------ //
    // State helpers
    // ------------------------------------------------------------------ //

    _q(id) {
      return this.shadowRoot.getElementById(id);
    }

    _refreshStatus() {
      const nameEl = this._q('frameName');
      if (!nameEl) return; // DOM not built yet

      const entity = this._hass && this._hass.states[this._config.entity];

      // Friendly name: strip " Battery" suffix that HA auto-adds.
      let name = this._config.name;
      if (!name && entity) {
        name = (entity.attributes.friendly_name || '')
          .replace(/\s+battery$/i, '')
          .trim() || this._config.entity;
      }
      nameEl.textContent = name || this._config.entity;

      const statusEl = this._q('frameStatus');
      if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') {
        statusEl.innerHTML = '<span class="dot-offline">● Offline</span>';
        return;
      }

      const pct = parseFloat(entity.state);
      const battText = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'} ${pct}% `;
      statusEl.innerHTML = `${battText}<span class="dot-online">● Online</span>`;
    }

    // ------------------------------------------------------------------ //
    // File selection
    // ------------------------------------------------------------------ //

    _onFileSelected(file) {
      this._selectedFile = file;

      // Release any previous object URL to avoid memory leaks.
      if (this._previewUrl) URL.revokeObjectURL(this._previewUrl);
      this._previewUrl = URL.createObjectURL(file);

      this._q('previewImg').src = this._previewUrl;
      this._q('previewCaption').textContent = file.name;
      this._q('preview').style.display = 'block';

      this._q('btnPick').style.display = 'none';
      this._q('btnSend').style.display = '';
      this._q('btnCancel').style.display = '';
      this._hideFeedback();
    }

    // ------------------------------------------------------------------ //
    // Image upload
    // ------------------------------------------------------------------ //

    async _sendImage() {
      if (!this._selectedFile || !this._hass) return;

      const btnSend   = this._q('btnSend');
      const btnCancel = this._q('btnCancel');

      btnSend.textContent = '⏳ Sending…';
      btnSend.disabled    = true;
      btnCancel.disabled  = true;

      const form = new FormData();
      form.append('entity_id', this._config.entity);
      form.append('image', this._selectedFile);

      let token;
      try {
        // The HA JS auth object exposes access_token.
        token = this._hass.auth.data.access_token;
      } catch (_) {
        token = null;
      }

      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const resp = await fetch('/api/fraimic/send_image', {
          method: 'POST',
          headers,
          body: form,
        });

        let result;
        try { result = await resp.json(); } catch (_) { result = {}; }

        if (resp.ok && result.success) {
          this._showFeedback('success', '✓ Image sent to frame!');
          setTimeout(() => this._reset(), 3000);
        } else {
          const msg = result.message || resp.statusText || `HTTP ${resp.status}`;
          this._showFeedback('error', `Failed: ${msg}`);
          btnSend.textContent = '⬆ Send to Frame';
          btnSend.disabled    = false;
          btnCancel.disabled  = false;
        }
      } catch (err) {
        this._showFeedback('error', `Network error: ${err.message}`);
        btnSend.textContent = '⬆ Send to Frame';
        btnSend.disabled    = false;
        btnCancel.disabled  = false;
      }
    }

    // ------------------------------------------------------------------ //
    // Helpers
    // ------------------------------------------------------------------ //

    _reset() {
      this._selectedFile = null;

      // Release the object URL.
      if (this._previewUrl) {
        URL.revokeObjectURL(this._previewUrl);
        this._previewUrl = null;
      }

      const fi = this._q('fileInput');
      if (fi) fi.value = '';

      const img = this._q('previewImg');
      if (img) img.src = '';

      this._q('preview').style.display   = 'none';
      this._q('btnPick').style.display   = '';
      this._q('btnSend').style.display   = 'none';
      this._q('btnCancel').style.display = 'none';

      const btnSend = this._q('btnSend');
      btnSend.textContent = '⬆ Send to Frame';
      btnSend.disabled    = false;
      this._q('btnCancel').disabled = false;

      this._hideFeedback();
    }

    _showFeedback(type, msg) {
      const el = this._q('feedback');
      el.className       = `feedback ${type}`;
      el.textContent     = msg;
      el.style.display   = 'block';
    }

    _hideFeedback() {
      const el = this._q('feedback');
      if (el) el.style.display = 'none';
    }
  }

  // Register the custom element.
  customElements.define('fraimic-card', FraimicCard);

  // Let the Lovelace card picker discover this card.
  window.customCards = window.customCards || [];
  window.customCards.push({
    type:             'fraimic-card',
    name:             'Fraimic Frame Card',
    description:      'Send images to a Fraimic e-ink frame from your dashboard.',
    preview:          false,
    documentationURL: 'https://github.com/dsackr/fraimic-homeassistant',
  });

  console.info(
    '%c FRAIMIC-CARD %c v' + CARD_VERSION + ' ',
    'background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px 0 0 3px;font-weight:600',
    'background:#1e293b;color:#fff;padding:2px 6px;border-radius:0 3px 3px 0',
  );
})();
