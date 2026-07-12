/**
 * Fraimic Frame Card
 * Custom Lovelace card showing a frame's current image, with full
 * upload/select-a-new-photo functionality.
 *
 * Config:
 *   type: custom:fraimic-card
 *   entity: sensor.frame_1_battery   # any Fraimic sensor for this frame
 *   name: Frame 1                    # optional friendly name override
 */

(function () {
  'use strict';

  const CARD_VERSION = '0.3.0';

  // Any Fraimic sensor works as the configured entity, but the battery
  // sensor is the one every frame device is guaranteed to have (and its
  // unique_id/entity_id both end in "_battery" -- see sensor.py), so it's
  // what the stub config and the editor's picker steer users toward.
  function _isFraimicBatteryEntity(hass, entityId) {
    if (!entityId.endsWith('_battery')) return false;
    const reg = hass && hass.entities && hass.entities[entityId];
    // hass.entities may be unpopulated in some embedding contexts (e.g. a
    // bare panel) -- fall back to the naming convention alone rather than
    // rejecting every entity outright.
    return !reg || reg.platform === 'fraimic';
  }

  // ------------------------------------------------------------------ //
  // Visual config editor -- without this, Lovelace's card picker falls
  // back to a raw YAML box and the user has to already know the exact
  // entity_id of the frame they want. That's exactly the manual, hand-
  // edited-config UX this integration otherwise avoids everywhere else.
  // ------------------------------------------------------------------ //

  class FraimicCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    connectedCallback() {
      this._render();
    }

    _render() {
      if (!this.shadowRoot) this.attachShadow({ mode: 'open' });

      let picker = this.shadowRoot.getElementById('picker');
      if (!picker) {
        this.shadowRoot.innerHTML = `
          <style>.wrap { padding: 12px 0; }</style>
          <div class="wrap">
            <ha-entity-picker id="picker" label="Frame (battery sensor)"></ha-entity-picker>
          </div>
        `;
        picker = this.shadowRoot.getElementById('picker');
        picker.includeDomains = ['sensor'];
        picker.entityFilter = (entityId) => _isFraimicBatteryEntity(this._hass, entityId);
        picker.addEventListener('value-changed', (ev) => {
          ev.stopPropagation();
          this._config = { ...this._config, entity: ev.detail.value };
          this.dispatchEvent(new CustomEvent('config-changed', {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          }));
        });
      }

      if (this._hass) picker.hass = this._hass;
      picker.value = this._config.entity || '';
    }
  }

  customElements.define('fraimic-card-editor', FraimicCardEditor);

  class FraimicCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._selectedFile = null;
      this._previewUrl = null;

      // On-frame preview state, resolved from /api/fraimic/frame_status.
      this._entryId = null;
      this._lastImageId = null;
      this._hasThumbnail = false;
      this._queued = false;
      this._lastEntityState = null;
      this._statusInFlight = false;

      // object: URL currently painted into the media <img>, plus the
      // backend URL it was loaded from (so repeat renders skip a refetch).
      this._mediaBlobUrl = null;
      this._mediaSourceUrl = null;
    }

    // ------------------------------------------------------------------ //
    // Lovelace card protocol
    // ------------------------------------------------------------------ //

    static getStubConfig(hass) {
      if (hass && hass.states) {
        const match = Object.keys(hass.states).find((eid) => _isFraimicBatteryEntity(hass, eid));
        if (match) return { entity: match };
      }
      return { entity: 'sensor.frame_1_battery' };
    }

    static getConfigElement() {
      return document.createElement('fraimic-card-editor');
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

      const entity = hass.states[this._config.entity];
      if (entity && entity !== this._lastEntityState) {
        this._lastEntityState = entity;
        this._fetchFrameStatus();
      } else if (!this._entryId && !this._statusInFlight) {
        // First render, or a previous lookup failed -- keep trying.
        this._fetchFrameStatus();
      }
    }

    // ------------------------------------------------------------------ //
    // DOM construction (called once from setConfig)
    // ------------------------------------------------------------------ //

    _build() {
      this.shadowRoot.innerHTML = `
        <style>
          *, *::before, *::after { box-sizing: border-box; }

          ha-card { overflow: hidden; }

          /* ---- media (on-frame image) ---- */
          .media {
            position: relative;
            height: 220px;
            background: var(--secondary-background-color, #f5f5f5);
            cursor: pointer;
            overflow: hidden;
          }
          .media img {
            display: none;
            width: 100%;
            height: 100%;
            object-fit: cover;
          }
          .media .placeholder {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 6px;
            font-size: 13px;
            color: var(--secondary-text-color);
            text-align: center;
            padding: 0 16px;
          }
          .media .placeholder .icon { font-size: 32px; opacity: .6; }

          .media .hint {
            position: absolute;
            inset: auto 0 0 0;
            padding: 6px 10px;
            font-size: 11px;
            color: #fff;
            background: linear-gradient(to top, rgba(0,0,0,.55), rgba(0,0,0,0));
            opacity: 0;
            transition: opacity .15s;
            pointer-events: none;
          }
          .media:hover .hint { opacity: 1; }

          .badge {
            position: absolute;
            top: 8px;
            left: 8px;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: .04em;
            color: #fff;
            background: rgba(0,0,0,.6);
            display: none;
          }
          .badge.queued {
            background: rgba(3,169,244,.85);
          }

          /* ---- footer ---- */
          .footer {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
          }
          .frame-name {
            flex: 1;
            min-width: 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--primary-text-color);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .frame-status {
            flex: 0 0 auto;
            font-size: 12px;
            color: var(--secondary-text-color);
            white-space: nowrap;
          }
          .dot-online  { color: var(--success-color,  #43a047); }
          .dot-offline { color: var(--error-color,    #e53935); }

          .gear {
            flex: 0 0 auto;
            width: 28px;
            height: 28px;
            border: none;
            border-radius: 50%;
            background: transparent;
            color: var(--secondary-text-color);
            font-size: 15px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          .gear:hover { background: var(--secondary-background-color, rgba(0,0,0,.06)); }

          /* ---- staged (picked-but-not-sent) actions ---- */
          .actions {
            display: none;
            gap: 8px;
            padding: 0 12px 12px;
          }
          button.act {
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
          button.act:active:not(:disabled) { transform: scale(.97); }
          button.act:disabled { opacity: .45; cursor: default; }

          .btn-send {
            background: var(--primary-color, #03a9f4);
            color: var(--text-primary-color, #fff);
          }
          .btn-cancel {
            background: var(--secondary-background-color, #eee);
            color: var(--primary-text-color);
            flex: 0 0 auto;
            padding-left: 14px;
            padding-right: 14px;
          }

          /* ---- feedback ---- */
          .feedback {
            display: none;
            margin: 0 12px 12px;
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
          <div class="media" id="media" title="Click to send a new photo to this frame">
            <img id="mediaImg" alt="" />
            <div class="placeholder" id="placeholder">
              <div class="icon">🖼</div>
              <div>No photo sent yet</div>
            </div>
            <div class="badge" id="badge">ON FRAME</div>
            <div class="hint">📷 Click to send a new photo</div>
          </div>

          <div class="footer">
            <span class="frame-name" id="frameName">Fraimic Frame</span>
            <span class="frame-status" id="frameStatus"></span>
            <button class="gear" id="gearBtn" title="Open Fraimic">⚙</button>
          </div>

          <div class="actions" id="actions">
            <button class="act btn-send" id="btnSend">⬆ Send to Frame</button>
            <button class="act btn-cancel" id="btnCancel">✕</button>
          </div>

          <div class="feedback" id="feedback"></div>

          <input type="file" id="fileInput"
            accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/*">
        </ha-card>
      `;

      // Wire up events.
      this._q('media').addEventListener('click', () => {
        if (this._selectedFile) return; // already staged -- use Send/Cancel
        this._q('fileInput').click();
      });

      this._q('fileInput').addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) this._onFileSelected(file);
      });

      this._q('btnSend').addEventListener('click', () => this._sendImage());
      this._q('btnCancel').addEventListener('click', () => this._reset());

      this._q('gearBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        this._openFraimicPanel();
      });

      // Populate status immediately if hass is already set.
      if (this._hass) {
        this._refreshStatus();
        this._fetchFrameStatus();
      }
    }

    // ------------------------------------------------------------------ //
    // State helpers
    // ------------------------------------------------------------------ //

    _q(id) {
      return this.shadowRoot.getElementById(id);
    }

    _authHeaders() {
      let token;
      try {
        token = this._hass.auth.data.access_token;
      } catch (_) {
        token = null;
      }
      return token ? { Authorization: `Bearer ${token}` } : {};
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
      const finalName = name || this._config.entity;
      if (nameEl.textContent !== finalName) nameEl.textContent = finalName;

      const statusEl = this._q('frameStatus');
      if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') {
        this._setStatusHtml(statusEl, '<span class="dot-offline">● Offline</span>');
        return;
      }

      const pct = parseFloat(entity.state);
      const battText = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'} ${pct}% `;
      this._setStatusHtml(statusEl, `${battText}<span class="dot-online">● Online</span>`);
    }

    // hass is re-assigned on every state change of ANY entity -- skip the
    // DOM write when this frame's status text is unchanged.
    _setStatusHtml(statusEl, html) {
      if (statusEl._fraimicLastStatus === html) return;
      statusEl._fraimicLastStatus = html;
      statusEl.innerHTML = html;
    }

    _openFraimicPanel() {
      history.pushState(null, '', '/fraimic');
      window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
    }

    // ------------------------------------------------------------------ //
    // On-frame image preview
    // ------------------------------------------------------------------ //

    async _fetchFrameStatus() {
      if (!this._hass || !this._config || this._statusInFlight) return;
      this._statusInFlight = true;
      try {
        const resp = await fetch(
          `/api/fraimic/frame_status?entity_id=${encodeURIComponent(this._config.entity)}`,
          { headers: this._authHeaders() }
        );
        if (resp.ok) {
          const data = await resp.json();
          this._entryId = data.entry_id;
          this._lastImageId = data.last_image_id;
          this._hasThumbnail = data.has_thumbnail;
          this._queued = data.queued;
        }
      } catch (_) {
        // Transient network error -- next hass update retries.
      } finally {
        this._statusInFlight = false;
      }
      this._renderOnFrameImage();
    }

    // Paints the confirmed on-frame image (never called while a local pick
    // is staged -- that shows its own preview via _onFileSelected instead).
    async _renderOnFrameImage() {
      if (!this._q('media') || this._selectedFile) return;

      let url = null;
      if (this._lastImageId) {
        url = `/api/fraimic/library/image/${this._lastImageId}?thumb=480`;
      } else if (this._hasThumbnail && this._entryId) {
        url = `/api/fraimic/frame/${this._entryId}/thumbnail`;
      }

      if (!url) {
        this._showPlaceholder();
      } else if (url !== this._mediaSourceUrl) {
        try {
          const resp = await fetch(url, { headers: this._authHeaders() });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const blob = await resp.blob();
          const objUrl = URL.createObjectURL(blob);

          if (this._mediaBlobUrl) URL.revokeObjectURL(this._mediaBlobUrl);
          this._mediaBlobUrl = objUrl;
          this._mediaSourceUrl = url;

          const img = this._q('mediaImg');
          img.src = objUrl;
          img.style.display = 'block';
          this._q('placeholder').style.display = 'none';
        } catch (_) {
          this._showPlaceholder();
        }
      }

      // Badge: a queued send (frame asleep) takes priority over the plain
      // "on frame" label -- it means what's showing is about to change,
      // not that it's the final state.
      if (this._queued) {
        this._setBadge('⏳ QUEUED', true);
      } else if (this._mediaSourceUrl) {
        this._setBadge('ON FRAME', false);
      } else {
        this._setBadge('', false);
      }
    }

    _showPlaceholder() {
      this._mediaSourceUrl = null;
      const img = this._q('mediaImg');
      img.style.display = 'none';
      img.src = '';
      this._q('placeholder').style.display = 'flex';
    }

    _setBadge(text, queued) {
      const badge = this._q('badge');
      if (!badge) return;
      if (!text) {
        badge.style.display = 'none';
        return;
      }
      badge.textContent = text;
      badge.classList.toggle('queued', !!queued);
      badge.style.display = 'block';
    }

    // ------------------------------------------------------------------ //
    // File selection
    // ------------------------------------------------------------------ //

    _onFileSelected(file) {
      this._selectedFile = file;

      // Release any previous object URL to avoid memory leaks.
      if (this._previewUrl) URL.revokeObjectURL(this._previewUrl);
      this._previewUrl = URL.createObjectURL(file);

      const img = this._q('mediaImg');
      img.src = this._previewUrl;
      img.style.display = 'block';
      this._q('placeholder').style.display = 'none';
      this._setBadge('', false);

      this._q('actions').style.display = 'flex';
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

      try {
        const resp = await fetch('/api/fraimic/send_image', {
          method: 'POST',
          headers: this._authHeaders(),
          body: form,
        });

        let result;
        try { result = await resp.json(); } catch (_) { result = {}; }

        if (resp.ok && result.success) {
          this._showFeedback('success', '✓ Image sent to frame!');
          setTimeout(() => {
            this._reset();
            this._fetchFrameStatus();
          }, 1500);
        } else if (result.queued) {
          this._showFeedback('success', '⏳ Frame is asleep — image queued, will send on wake.');
          setTimeout(() => {
            this._reset();
            this._fetchFrameStatus();
          }, 1500);
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

      this._q('actions').style.display = 'none';

      const btnSend = this._q('btnSend');
      btnSend.textContent = '⬆ Send to Frame';
      btnSend.disabled    = false;
      this._q('btnCancel').disabled = false;

      this._hideFeedback();

      // Force the on-frame image to repaint even if the URL hasn't changed
      // yet (e.g. a failed send left the placeholder showing).
      this._mediaSourceUrl = null;
      this._renderOnFrameImage();
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
    description:      'Show what\'s on a Fraimic e-ink frame and send it a new photo from your dashboard.',
    preview:          false,
    documentationURL: 'https://github.com/dsackr/fraimic-homeassistant',
  });

  console.info(
    '%c FRAIMIC-CARD %c v' + CARD_VERSION + ' ',
    'background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px 0 0 3px;font-weight:600',
    'background:#1e293b;color:#fff;padding:2px 6px;border-radius:0 3px 3px 0',
  );
})();
