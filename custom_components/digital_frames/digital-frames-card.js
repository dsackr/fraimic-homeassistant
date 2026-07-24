/**
 * Fraimic Frame Card
 * Custom Lovelace card showing a frame's latest displayed image (photos,
 * productivity feeds, xOTD renders alike), with full manage-the-frame
 * functionality: upload a photo, pick a library image or daily skill to
 * send, change orientation, and adjust how the current photo is cropped.
 *
 * Config (all set via the visual editor -- no YAML required):
 *   type: custom:fraimic-card
 *   entry_id: <config entry id of the frame>   # picked from a list
 *   name: My Frame                             # optional name override
 *
 * Legacy configs that used `entity: sensor.frame_1_battery` keep working:
 * the card resolves them to the owning frame via the frames API.
 */

(function () {
  'use strict';

  const CARD_VERSION = '0.5.0';
  const FRAMES_URL = '/api/digital_frames/frames';
  const FRAMES_REFRESH_MS = 30000;

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function skillIcon(contentMode) {
    return {
      joke: '😂',
      quote: '💬',
      scripture: '📖',
      word: '🔤',
      image_feed: '🖼',
      image_album: '🖼',
    }[contentMode] || '◈';
  }

  function authHeaders(hass) {
    let token;
    try {
      token = hass.auth.data.access_token;
    } catch (_) {
      token = null;
    }
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // Centered crop rectangle (normalized x0,y0,x1,y1) matching targetW:targetH,
  // as large as the original image allows -- same math as the sidebar
  // panel's crop editor so both produce identical default framings.
  function computeCoverBox(naturalW, naturalH, targetW, targetH, centerX = 0.5, centerY = 0.5) {
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

  // AR-locked resize: the corner opposite the dragged handle stays fixed.
  // Ported verbatim from the panel's _editorResizeBox.
  function resizeBox(startBox, handle, dxNorm, dyNorm, ar) {
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

  // ------------------------------------------------------------------ //
  // Visual config editor: a dropdown of frames (by name), not entities.
  // ------------------------------------------------------------------ //

  class DigitalFramesCardEditor extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._frames = null;
      this._loading = false;
    }

    setConfig(config) {
      this._config = { ...(config || {}) };
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._frames && !this._loading) this._loadFrames();
      this._render();
    }

    async _loadFrames() {
      if (!this._hass) return;
      this._loading = true;
      try {
        const resp = await fetch(FRAMES_URL, { headers: authHeaders(this._hass) });
        if (resp.ok) {
          const data = await resp.json();
          this._frames = data.frames || [];
        }
      } catch (_) {
        // Leave null; a hass update retries.
      } finally {
        this._loading = false;
      }
      this._render();
    }

    // The frame this config points at: entry_id directly, or (legacy
    // configs) the frame owning the configured battery entity.
    _selectedEntryId() {
      if (this._config.entry_id) return this._config.entry_id;
      if (this._config.entity && this._frames) {
        const match = this._frames.find((f) => f.battery_entity_id === this._config.entity);
        if (match) return match.entry_id;
      }
      return '';
    }

    _emit() {
      this.dispatchEvent(new CustomEvent('config-changed', {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      }));
    }

    _render() {
      const root = this.shadowRoot;
      if (!root.getElementById('wrap')) {
        root.innerHTML = `
          <style>
            .wrap { padding: 8px 0; display: flex; flex-direction: column; gap: 14px; }
            label { display: block; font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px; }
            select, input {
              width: 100%;
              box-sizing: border-box;
              padding: 10px;
              border: 1px solid var(--divider-color, #ccc);
              border-radius: 6px;
              background: var(--card-background-color, #fff);
              color: var(--primary-text-color);
              font-size: 14px;
            }
            .empty { font-size: 13px; color: var(--secondary-text-color); }
          </style>
          <div class="wrap" id="wrap">
            <div>
              <label for="frame">Frame</label>
              <select id="frame"></select>
              <div class="empty" id="empty" style="display:none;margin-top:6px">
                No Fraimic frames found yet — add one from Settings → Devices &amp; Services.
              </div>
            </div>
            <div>
              <label for="name">Name (optional — overrides the frame's name)</label>
              <input id="name" type="text" placeholder="">
            </div>
          </div>
        `;
        root.getElementById('frame').addEventListener('change', (e) => {
          // Writing entry_id drops any legacy entity: key -- entry_id is
          // the canonical config from here on.
          const { entity, ...rest } = this._config;
          this._config = { ...rest, entry_id: e.target.value };
          this._emit();
        });
        root.getElementById('name').addEventListener('input', (e) => {
          const value = e.target.value.trim();
          this._config = { ...this._config };
          if (value) this._config.name = value;
          else delete this._config.name;
          this._emit();
        });
      }

      const select = root.getElementById('frame');
      const empty = root.getElementById('empty');
      const frames = this._frames || [];
      const selected = this._selectedEntryId();

      let options = frames.map((f) => {
        const size = f.size ? ` (${f.size}")` : '';
        return `<option value="${esc(f.entry_id)}">${esc(f.title)}${esc(size)}</option>`;
      }).join('');
      if (!selected) options = `<option value="" disabled>${this._frames ? 'Choose a frame…' : 'Loading frames…'}</option>` + options;

      if (select._fraimicOptions !== options) {
        select._fraimicOptions = options;
        select.innerHTML = options;
      }
      select.value = selected;
      empty.style.display = this._frames && !frames.length ? 'block' : 'none';

      const nameInput = root.getElementById('name');
      if (document.activeElement !== nameInput && nameInput.value !== (this._config.name || '')) {
        nameInput.value = this._config.name || '';
      }
    }
  }

  customElements.define('fraimic-card-editor', DigitalFramesCardEditor);

  // ------------------------------------------------------------------ //
  // The card
  // ------------------------------------------------------------------ //

  class DigitalFramesCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });

      this._frames = null;         // /api/digital_frames/frames payload
      this._frame = null;          // this card's frame record
      this._framesFetchedAt = 0;
      this._framesInFlight = false;

      // What the media area currently shows (confirmed on-frame state).
      this._mediaBlobUrl = null;   // object URL painted into <img>
      this._mediaSourceUrl = null; // backend URL it came from
      this._frameThumbEtag = null; // ETag of /frame/{id}/thumbnail

      // Staged-but-not-sent pick: {kind:'file',file} | {kind:'image',imageId}
      // | {kind:'skill',skillId,name,mode}
      this._staged = null;
      this._stagedPreviewUrl = null;

      // Picker state
      this._pickerMode = null;     // 'photos' | 'daily' | null
      this._pickerToken = 0;
      this._albums = null;
      this._thumbQueue = [];
      this._thumbActive = 0;

      // Crop editor state
      this._crop = null;           // active session or null
      this._cropImgUrl = null;
      this._cropDrag = null;
      this._onCropMove = this._onCropMove.bind(this);
      this._onCropUp = this._onCropUp.bind(this);
    }

    // ------------------------------------------------------------------ //
    // Lovelace card protocol
    // ------------------------------------------------------------------ //

    static getStubConfig(hass) {
      // The stub can't await the frames API, so steer through the one
      // entity every frame device has; the card resolves it to its frame.
      if (hass && hass.states) {
        const match = Object.keys(hass.states).find((eid) => {
          if (!eid.endsWith('_battery')) return false;
          const reg = hass.entities && hass.entities[eid];
          return reg ? reg.platform === 'fraimic' : false;
        });
        if (match) return { entity: match };
      }
      return {};
    }

    static getConfigElement() {
      return document.createElement('fraimic-card-editor');
    }

    setConfig(config) {
      this._config = config || {};
      // _build() unconditionally replaces the whole shadow DOM below, and
      // HA's card-editor live preview calls setConfig() on every config
      // change (e.g. every keystroke in the editor's Name field, not just
      // entry_id/entity) -- any staged-but-unsent pick or open crop session
      // must be torn down here too, or the freshly rebuilt DOM's
      // default-hidden state (actions bar, crop overlay) desyncs from
      // _staged/_crop staying truthy, with nothing left in the new DOM to
      // reach _unstage()/_closeCrop() from and the card stuck until reload.
      this._teardownVolatileState();
      this._build();
    }

    // Revokes every blob URL this card can be holding and removes the
    // window-level listeners the crop-drag session registers. Shared by
    // setConfig() (about to blow away the DOM that referenced them) and
    // disconnectedCallback() (the element itself is being removed --
    // HA recreates Lovelace cards on dashboard/view changes, never reuses
    // one, so anything left here leaks for the life of the browser tab).
    _teardownVolatileState() {
      if (this._stagedPreviewUrl) {
        URL.revokeObjectURL(this._stagedPreviewUrl);
        this._stagedPreviewUrl = null;
      }
      if (this._cropImgUrl) {
        URL.revokeObjectURL(this._cropImgUrl);
        this._cropImgUrl = null;
      }
      if (this._mediaBlobUrl) {
        URL.revokeObjectURL(this._mediaBlobUrl);
        this._mediaBlobUrl = null;
      }
      this._staged = null;
      this._crop = null;
      this._cropDrag = null;
      this._pickerMode = null;
      this._mediaSourceUrl = null;
      this._frameThumbEtag = null;
      window.removeEventListener('pointermove', this._onCropMove);
      window.removeEventListener('pointerup', this._onCropUp);
      if (this._onCropResize) window.removeEventListener('resize', this._onCropResize);
    }

    disconnectedCallback() {
      this._teardownVolatileState();
    }

    getCardSize() {
      return 5;
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      this._refreshFooter();

      // Refetch frame state when this frame's battery entity changed
      // (coordinator poll landed) or on a slow heartbeat -- hass is
      // re-assigned on every state change of ANY entity, so both checks
      // are cheap comparisons.
      const watched = [];
      if (this._frame && this._frame.battery_entity_id) {
        watched.push(this._frame.battery_entity_id);
      } else if (this._config && this._config.entity) {
        watched.push(this._config.entity);
      }
      let changed = false;
      for (const eid of watched) {
        const st = hass.states[eid];
        if (st !== this._lastStates?.[eid]) {
          changed = true;
          break;
        }
      }
      if (changed || first || Date.now() - this._framesFetchedAt > FRAMES_REFRESH_MS) {
        this._lastStates = {};
        for (const eid of watched) this._lastStates[eid] = hass.states[eid];
        this._refreshFrames();
      }
    }

    // ------------------------------------------------------------------ //
    // DOM
    // ------------------------------------------------------------------ //

    _build() {
      this.shadowRoot.innerHTML = `
        <style>
          *, *::before, *::after { box-sizing: border-box; }
          ha-card { overflow: hidden; }

          /* ---- media (on-frame image) ---- */
          .media {
            position: relative;
            width: 100%;
            aspect-ratio: 3 / 2;
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
          .media img.render { object-fit: contain; background: #14181c; }
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
          .media .placeholder .icon { font-size: 34px; opacity: .6; }
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
          .badge.queued  { background: rgba(3,169,244,.85); }
          .badge.preview { background: rgba(255,152,0,.9); }

          /* ---- footer ---- */
          .footer {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 10px 12px 6px;
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
          .dot-online  { color: var(--success-color, #43a047); }
          .dot-offline { color: var(--error-color, #e53935); }

          .iconbtn {
            flex: 0 0 auto;
            width: 28px;
            height: 28px;
            border: none;
            border-radius: 6px;
            background: transparent;
            color: var(--secondary-text-color);
            font-size: 14px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0;
          }
          .iconbtn:hover { background: var(--secondary-background-color, rgba(0,0,0,.06)); }
          .iconbtn.active {
            color: var(--primary-color, #03a9f4);
            background: rgba(3,169,244,.12);
          }
          .iconbtn svg { display: block; }

          /* ---- toolbar ---- */
          .toolbar {
            display: flex;
            gap: 6px;
            padding: 4px 12px 12px;
            flex-wrap: wrap;
          }
          .toolbar button {
            flex: 1 1 auto;
            padding: 7px 8px;
            border: 1px solid var(--divider-color, rgba(0,0,0,.12));
            border-radius: 6px;
            background: transparent;
            color: var(--primary-text-color);
            font-size: 12px;
            cursor: pointer;
            white-space: nowrap;
          }
          .toolbar button:hover:not(:disabled) { background: var(--secondary-background-color, rgba(0,0,0,.05)); }
          .toolbar button:disabled { opacity: .4; cursor: default; }
          .toolbar button.open { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); }

          /* ---- picker (photos / daily) ---- */
          .picker { display: none; padding: 0 12px 12px; }
          .picker .picker-head {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
          }
          .picker select {
            flex: 1;
            min-width: 0;
            padding: 6px 8px;
            border: 1px solid var(--divider-color, #ccc);
            border-radius: 6px;
            background: var(--card-background-color, #fff);
            color: var(--primary-text-color);
            font-size: 12px;
          }
          .picker-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
            gap: 6px;
            max-height: 240px;
            overflow-y: auto;
          }
          .picker-cell {
            position: relative;
            aspect-ratio: 1;
            border-radius: 6px;
            overflow: hidden;
            cursor: pointer;
            background: var(--secondary-background-color, #eee);
            border: 2px solid transparent;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
          }
          .picker-cell.selected { border-color: var(--primary-color, #03a9f4); }
          .picker-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
          .picker-cell .skill-label {
            position: absolute;
            inset: auto 0 0 0;
            font-size: 9px;
            padding: 2px 4px;
            background: rgba(0,0,0,.55);
            color: #fff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            text-align: center;
          }
          .picker-note {
            font-size: 12px;
            color: var(--secondary-text-color);
            padding: 8px 0;
          }

          /* ---- staged actions ---- */
          .actions { display: none; gap: 8px; padding: 0 12px 12px; }
          button.act {
            flex: 1;
            padding: 9px 12px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            line-height: 1.2;
          }
          button.act:active:not(:disabled) { transform: scale(.97); }
          button.act:disabled { opacity: .45; cursor: default; }
          .btn-send { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
          .btn-cancel {
            background: var(--secondary-background-color, #eee);
            color: var(--primary-text-color);
            flex: 0 0 auto;
            padding: 9px 14px;
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
          .feedback.success { background: rgba(67,160,71,.12); color: var(--success-color, #2e7d32); }
          .feedback.error   { background: rgba(229,57,53,.10); color: var(--error-color, #c62828); }

          input[type="file"] { display: none; }

          /* ---- crop editor (full-screen overlay) ---- */
          .crop-overlay {
            position: fixed;
            inset: 0;
            z-index: 10000;
            display: none;
            flex-direction: column;
            background: rgba(10, 12, 15, .92);
          }
          .crop-header {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            color: #fff;
          }
          .crop-header .title {
            flex: 1;
            min-width: 0;
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .crop-header button {
            border: none;
            background: rgba(255,255,255,.12);
            color: #fff;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
            cursor: pointer;
          }
          .crop-stage {
            position: relative;
            flex: 1;
            margin: 0 14px;
            overflow: hidden;
            touch-action: none;
          }
          .crop-stage img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            user-select: none;
            -webkit-user-drag: none;
          }
          .crop-box {
            position: absolute;
            border: 2px solid #fff;
            box-shadow: 0 0 0 9999px rgba(0,0,0,.55);
            cursor: move;
            touch-action: none;
          }
          .crop-handle {
            position: absolute;
            width: 18px;
            height: 18px;
            background: #fff;
            border-radius: 50%;
            touch-action: none;
          }
          .crop-handle.tl { left: -9px; top: -9px; cursor: nwse-resize; }
          .crop-handle.tr { right: -9px; top: -9px; cursor: nesw-resize; }
          .crop-handle.bl { left: -9px; bottom: -9px; cursor: nesw-resize; }
          .crop-handle.br { right: -9px; bottom: -9px; cursor: nwse-resize; }
          .crop-actions {
            display: flex;
            gap: 8px;
            padding: 12px 14px calc(14px + env(safe-area-inset-bottom, 0px));
            flex-wrap: wrap;
          }
          .crop-actions button {
            flex: 1 1 auto;
            padding: 10px 14px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
          }
          .crop-actions .primary { background: var(--primary-color, #03a9f4); color: #fff; }
          .crop-actions .ghost   { background: rgba(255,255,255,.12); color: #fff; }
          .crop-actions button:disabled { opacity: .5; cursor: default; }
          .crop-fb {
            display: none;
            margin: 0 14px;
            padding: 7px 10px;
            border-radius: 6px;
            font-size: 12px;
          }
          .crop-fb.success { background: rgba(67,160,71,.25); color: #b9e6bb; }
          .crop-fb.error   { background: rgba(229,57,53,.25); color: #ffb4b0; }
        </style>

        <ha-card>
          <div class="media" id="media" title="Click to choose a photo for this frame">
            <img id="mediaImg" alt="" />
            <div class="placeholder" id="placeholder">
              <div class="icon">🖼</div>
              <div id="placeholderText">Nothing sent yet — click to choose a photo</div>
            </div>
            <div class="badge" id="badge">ON FRAME</div>
            <div class="hint" id="mediaHint">🖼 Click to choose a photo</div>
          </div>

          <div class="footer">
            <span class="frame-name" id="frameName">Frame</span>
            <span class="frame-status" id="frameStatus"></span>
            <button class="iconbtn" id="orientPortrait" title="Portrait (next send)" style="display:none">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>
            </button>
            <button class="iconbtn" id="orientLandscape" title="Landscape (next send)" style="display:none">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>
            </button>
            <button class="iconbtn" id="gearBtn" title="Open Digital Frames">⚙</button>
          </div>

          <div class="toolbar" id="toolbar">
            <button id="btnUpload">⬆ Upload</button>
            <button id="btnPhotos">🖼 Photos</button>
            <button id="btnDaily">✨ Daily</button>
            <button id="btnCrop" disabled title="Adjust how the current photo is cropped on the frame">✂ Crop</button>
          </div>

          <div class="picker" id="picker">
            <div class="picker-head" id="pickerHead" style="display:none">
              <select id="albumSelect"></select>
            </div>
            <div class="picker-grid" id="pickerGrid"></div>
          </div>

          <div class="actions" id="actions">
            <button class="act btn-send" id="btnSend">⬆ Send to Frame</button>
            <button class="act btn-cancel" id="btnCancel">✕</button>
          </div>

          <div class="feedback" id="feedback"></div>

          <input type="file" id="fileInput"
            accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/*">
        </ha-card>

        <div class="crop-overlay" id="cropOverlay">
          <div class="crop-header">
            <div class="title" id="cropTitle">Adjust crop</div>
            <button id="cropClose">✕ Close</button>
          </div>
          <div class="crop-stage" id="cropStage">
            <img id="cropImg" alt="" draggable="false" />
            <div class="crop-box" id="cropBox" style="display:none">
              <div class="crop-handle tl" data-handle="tl"></div>
              <div class="crop-handle tr" data-handle="tr"></div>
              <div class="crop-handle bl" data-handle="bl"></div>
              <div class="crop-handle br" data-handle="br"></div>
            </div>
          </div>
          <div class="crop-fb" id="cropFb"></div>
          <div class="crop-actions">
            <button class="primary" id="cropSaveSend">✂ Save &amp; Send to Frame</button>
            <button class="ghost" id="cropReset">↺ Reset to automatic</button>
          </div>
        </div>
      `;

      // ---- events ----
      this._q('media').addEventListener('click', () => {
        if (this._staged) return; // staged pick pending -- use Send/Cancel
        this._togglePicker('photos');
      });
      this._q('fileInput').addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) this._stageFile(file);
      });
      this._q('btnUpload').addEventListener('click', () => this._q('fileInput').click());
      this._q('btnPhotos').addEventListener('click', () => this._togglePicker('photos'));
      this._q('btnDaily').addEventListener('click', () => this._togglePicker('daily'));
      this._q('btnCrop').addEventListener('click', () => this._openCrop());
      this._q('albumSelect').addEventListener('change', () => this._loadPickerGrid());
      this._q('btnSend').addEventListener('click', () => this._send());
      this._q('btnCancel').addEventListener('click', () => this._unstage());
      this._q('gearBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        history.pushState(null, '', '/digital_frames');
        window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
      });
      this._q('orientPortrait').addEventListener('click', () => this._setOrientation('portrait'));
      this._q('orientLandscape').addEventListener('click', () => this._setOrientation('landscape'));

      // Crop editor
      this._q('cropClose').addEventListener('click', () => this._closeCrop());
      this._q('cropSaveSend').addEventListener('click', () => this._cropSaveSend());
      this._q('cropReset').addEventListener('click', () => this._cropReset());
      const box = this._q('cropBox');
      box.addEventListener('pointerdown', (e) => {
        if (e.target.classList.contains('crop-handle')) return;
        this._cropBeginDrag(e, 'move', null);
      });
      box.querySelectorAll('.crop-handle').forEach((h) => {
        h.addEventListener('pointerdown', (e) => this._cropBeginDrag(e, 'resize', h.dataset.handle));
      });

      if (this._hass) {
        this._refreshFooter();
        this._refreshFrames(true);
      }
    }

    _q(id) {
      return this.shadowRoot.getElementById(id);
    }

    _authHeaders() {
      return authHeaders(this._hass);
    }

    // ------------------------------------------------------------------ //
    // Frame state
    // ------------------------------------------------------------------ //

    async _refreshFrames(force = false) {
      if (!this._hass || !this._config || this._framesInFlight) return;
      if (!force && Date.now() - this._framesFetchedAt < 2000) return;
      this._framesInFlight = true;
      try {
        const resp = await fetch(FRAMES_URL, { headers: this._authHeaders() });
        if (resp.ok) {
          const data = await resp.json();
          this._frames = data.frames || [];
          this._framesFetchedAt = Date.now();
          this._frame = this._resolveFrame();
        }
      } catch (_) {
        // Transient -- next hass update retries.
      } finally {
        this._framesInFlight = false;
      }
      this._refreshFooter();
      this._renderMedia();
      this._refreshToolbar();
    }

    _resolveFrame() {
      const frames = this._frames || [];
      if (this._config.entry_id) {
        return frames.find((f) => f.entry_id === this._config.entry_id) || null;
      }
      if (this._config.entity) {
        return frames.find((f) => f.battery_entity_id === this._config.entity) || null;
      }
      return null;
    }

    _refreshFooter() {
      const nameEl = this._q('frameName');
      if (!nameEl) return; // DOM not built yet

      let name = this._config.name || (this._frame && this._frame.title);
      if (!name && this._config.entity && this._hass) {
        const st = this._hass.states[this._config.entity];
        name = st && (st.attributes.friendly_name || '').replace(/\s+battery$/i, '').trim();
      }
      const finalName = name || 'Frame';
      if (nameEl.textContent !== finalName) nameEl.textContent = finalName;

      // Status: battery entity when known; falls back to /frames "online".
      const statusEl = this._q('frameStatus');
      const battEid = (this._frame && this._frame.battery_entity_id) || this._config.entity;
      const st = battEid && this._hass && this._hass.states[battEid];
      let html;
      if (st && st.state !== 'unavailable' && st.state !== 'unknown') {
        const pct = parseFloat(st.state);
        const battText = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'} ${pct}% `;
        html = `${battText}<span class="dot-online">● Online</span>`;
      } else if (!st && this._frame) {
        html = this._frame.online
          ? '<span class="dot-online">● Online</span>'
          : '<span class="dot-offline">● Offline</span>';
      } else {
        html = '<span class="dot-offline">● Offline</span>';
      }
      if (statusEl._fraimicLastStatus !== html) {
        statusEl._fraimicLastStatus = html;
        statusEl.innerHTML = html;
      }

      // Orientation buttons
      const hasOrient = !!(this._frame && this._frame.orientation_entity_id);
      const pBtn = this._q('orientPortrait');
      const lBtn = this._q('orientLandscape');
      pBtn.style.display = hasOrient ? '' : 'none';
      lBtn.style.display = hasOrient ? '' : 'none';
      if (this._frame) {
        pBtn.classList.toggle('active', this._frame.orientation === 'portrait');
        lBtn.classList.toggle('active', this._frame.orientation === 'landscape');
      }

      // Media aspect follows the frame's effective composition dims.
      const media = this._q('media');
      if (this._frame && this._frame.width && this._frame.height) {
        const ratio = `${this._frame.width} / ${this._frame.height}`;
        if (media.style.aspectRatio !== ratio) media.style.aspectRatio = ratio;
      }

      if (!this._frame && this._frames && !this._config.entry_id && !this._config.entity) {
        this._q('placeholderText').textContent = 'Open the card editor and choose a frame';
      }
    }

    _refreshToolbar() {
      // Crop works on the library image currently on (or staged for) the
      // frame -- uploads and text skills have no library original to crop.
      const imageId = this._cropTargetImageId();
      const btn = this._q('btnCrop');
      btn.disabled = !imageId || !this._frame;
      btn.title = imageId
        ? 'Adjust how this photo is cropped on the frame'
        : 'Crop needs a library photo on the frame (uploads and daily feeds can\'t be re-cropped)';
    }

    _cropTargetImageId() {
      if (this._staged && this._staged.kind === 'image') return this._staged.imageId;
      if (this._staged) return null;
      return (this._frame && this._frame.last_image_id) || null;
    }

    // ------------------------------------------------------------------ //
    // Media (confirmed on-frame image)
    // ------------------------------------------------------------------ //

    async _renderMedia() {
      if (!this._q('media') || this._staged) return;

      const frame = this._frame;
      let url = null;
      let isRender = false;
      if (frame && frame.last_image_id) {
        url = `/api/digital_frames/library/image/${frame.last_image_id}?thumb=480`;
      } else if (frame && frame.has_thumbnail) {
        // The frame's own render preview: photos sent by upload, and
        // xOTD/daily text renders (quantized PNG) -- contain, don't crop.
        url = `/api/digital_frames/frame/${frame.entry_id}/thumbnail`;
        isRender = true;
      }

      if (!url) {
        this._showPlaceholder();
      } else {
        try {
          const headers = this._authHeaders();
          // The frame-thumbnail URL is stable but its content changes per
          // send -- revalidate by ETag so a new render repaints.
          if (isRender && this._frameThumbEtag && url === this._mediaSourceUrl) {
            headers['If-None-Match'] = this._frameThumbEtag;
          } else if (url === this._mediaSourceUrl) {
            // Library thumb URLs are immutable -- nothing to refetch.
            this._updateBadge();
            return;
          }
          const resp = await fetch(url, { headers });
          if (resp.status === 304) {
            this._updateBadge();
            return;
          }
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          this._frameThumbEtag = isRender ? resp.headers.get('ETag') : null;
          const blob = await resp.blob();
          if (this._staged) return; // user staged something mid-fetch
          const objUrl = URL.createObjectURL(blob);
          if (this._mediaBlobUrl) URL.revokeObjectURL(this._mediaBlobUrl);
          this._mediaBlobUrl = objUrl;
          this._mediaSourceUrl = url;

          const img = this._q('mediaImg');
          img.src = objUrl;
          img.classList.toggle('render', isRender);
          img.style.display = 'block';
          this._q('placeholder').style.display = 'none';
        } catch (_) {
          this._showPlaceholder();
        }
      }
      this._updateBadge();
    }

    _updateBadge() {
      if (this._staged) {
        this._setBadge('PREVIEW', 'preview');
      } else if (this._frame && this._frame.queued) {
        this._setBadge('⏳ QUEUED', 'queued');
      } else if (this._mediaSourceUrl) {
        this._setBadge('ON FRAME', '');
      } else {
        this._setBadge('', '');
      }
    }

    _setBadge(text, variant) {
      const badge = this._q('badge');
      if (!badge) return;
      if (!text) {
        badge.style.display = 'none';
        return;
      }
      badge.textContent = text;
      badge.className = `badge${variant ? ' ' + variant : ''}`;
      badge.style.display = 'block';
    }

    _showPlaceholder() {
      this._mediaSourceUrl = null;
      this._frameThumbEtag = null;
      const img = this._q('mediaImg');
      img.style.display = 'none';
      img.src = '';
      this._q('placeholder').style.display = 'flex';
    }

    // ------------------------------------------------------------------ //
    // Picker (photos / daily skills)
    // ------------------------------------------------------------------ //

    _togglePicker(mode) {
      if (this._pickerMode === mode) {
        this._closePicker();
        return;
      }
      this._pickerMode = mode;
      this._q('btnPhotos').classList.toggle('open', mode === 'photos');
      this._q('btnDaily').classList.toggle('open', mode === 'daily');
      this._q('picker').style.display = 'block';
      this._q('pickerHead').style.display = mode === 'photos' ? 'flex' : 'none';
      this._hideFeedback();
      if (mode === 'photos') this._loadAlbums();
      this._loadPickerGrid();
    }

    _closePicker() {
      this._pickerMode = null;
      this._pickerToken++;
      this._q('picker').style.display = 'none';
      this._q('btnPhotos').classList.remove('open');
      this._q('btnDaily').classList.remove('open');
      this._q('pickerGrid').innerHTML = '';
      this._thumbQueue = [];
    }

    async _loadAlbums() {
      const select = this._q('albumSelect');
      if (this._albums === null) {
        try {
          const resp = await fetch('/api/digital_frames/library/albums', { headers: this._authHeaders() });
          const data = await resp.json();
          this._albums = data.albums || [];
        } catch (_) {
          this._albums = [];
        }
      }
      const prev = select.value;
      select.innerHTML = '<option value="">All Photos</option>' +
        this._albums.map((a) => `<option value="${esc(a.name)}">${esc(a.name)}</option>`).join('');
      select.value = prev && [...select.options].some((o) => o.value === prev) ? prev : '';
    }

    async _loadPickerGrid() {
      const mode = this._pickerMode;
      if (!mode) return;
      const token = ++this._pickerToken;
      const grid = this._q('pickerGrid');
      grid.innerHTML = '<div class="picker-note">Loading…</div>';
      this._thumbQueue = [];

      if (mode === 'daily') {
        let skills = [];
        try {
          const resp = await fetch('/api/digital_frames/skills', { headers: this._authHeaders() });
          const data = await resp.json();
          skills = data.skills || [];
        } catch (_) { /* fall through to empty-state */ }
        if (token !== this._pickerToken) return;
        if (!skills.length) {
          grid.innerHTML = '<div class="picker-note">No live content yet — create some in the Digital Frames panel\'s Live tab.</div>';
          return;
        }
        grid.innerHTML = '';
        for (const skill of skills) {
          const cell = document.createElement('div');
          cell.className = 'picker-cell';
          cell.title = skill.name;
          cell.innerHTML = `
            <div style="font-size:24px">${skillIcon(skill.content_mode)}</div>
            <div class="skill-label">${esc(skill.name)}</div>
          `;
          cell.addEventListener('click', () => this._stageSkill(skill));
          grid.appendChild(cell);
        }
        return;
      }

      // photos
      const album = this._q('albumSelect').value;
      let images = [];
      try {
        const url = album
          ? `/api/digital_frames/library/list?album=${encodeURIComponent(album)}`
          : '/api/digital_frames/library/list';
        const resp = await fetch(url, { headers: this._authHeaders() });
        const data = await resp.json();
        images = data.images || [];
      } catch (_) { /* fall through to empty-state */ }
      if (token !== this._pickerToken) return;
      if (!images.length) {
        grid.innerHTML = '<div class="picker-note">No photos here yet — upload some, or manage the library in the Fraimic panel.</div>';
        return;
      }
      grid.innerHTML = '';
      const currentId = this._frame && this._frame.last_image_id;
      for (const image of images) {
        const cell = document.createElement('div');
        cell.className = 'picker-cell';
        cell.title = image.filename || '';
        cell.textContent = '🖼';
        if (image.image_id === currentId) cell.classList.add('selected');
        cell.addEventListener('click', () => this._stageImage(image));
        grid.appendChild(cell);
        this._queueThumb(image.image_id, cell, token);
      }
    }

    _queueThumb(imageId, cell, token) {
      this._thumbQueue.push({ imageId, cell, token });
      this._pumpThumbQueue();
    }

    async _pumpThumbQueue() {
      if (this._thumbActive >= 5) return;
      const job = this._thumbQueue.shift();
      if (!job) return;
      this._thumbActive++;
      try {
        if (job.token === this._pickerToken) {
          const resp = await fetch(
            `/api/digital_frames/library/image/${job.imageId}?thumb=200`,
            { headers: this._authHeaders() }
          );
          if (resp.ok && job.token === this._pickerToken) {
            const blob = await resp.blob();
            const img = document.createElement('img');
            img.src = URL.createObjectURL(blob);
            img.addEventListener('load', () => URL.revokeObjectURL(img.src), { once: true });
            job.cell.textContent = '';
            job.cell.appendChild(img);
          }
        }
      } catch (_) {
        // Keep the 🖼 fallback glyph.
      } finally {
        this._thumbActive--;
        this._pumpThumbQueue();
      }
    }

    // ------------------------------------------------------------------ //
    // Staging + send
    // ------------------------------------------------------------------ //

    _stageFile(file) {
      this._setStaged({ kind: 'file', file }, URL.createObjectURL(file), false);
    }

    _stageImage(image) {
      this._setStaged({ kind: 'image', imageId: image.image_id }, null, false);
      // Preview via authorized blob fetch (img src can't carry the header).
      const staged = this._staged;
      fetch(`/api/digital_frames/library/image/${image.image_id}?thumb=480`, { headers: this._authHeaders() })
        .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((blob) => {
          if (this._staged !== staged) return;
          this._stagedPreviewUrl = URL.createObjectURL(blob);
          const img = this._q('mediaImg');
          img.src = this._stagedPreviewUrl;
          img.classList.remove('render');
          img.style.display = 'block';
          this._q('placeholder').style.display = 'none';
        })
        .catch(() => { /* preview is cosmetic; Send still works */ });
    }

    _stageSkill(skill) {
      this._setStaged(
        { kind: 'skill', skillId: skill.skill_id, name: skill.name, mode: skill.content_mode },
        null, true
      );
    }

    _setStaged(staged, previewUrl, isSkill) {
      if (this._stagedPreviewUrl) {
        URL.revokeObjectURL(this._stagedPreviewUrl);
        this._stagedPreviewUrl = null;
      }
      this._staged = staged;
      this._closePicker();
      this._hideFeedback();

      const img = this._q('mediaImg');
      const ph = this._q('placeholder');
      if (previewUrl) {
        this._stagedPreviewUrl = previewUrl;
        img.src = previewUrl;
        img.classList.remove('render');
        img.style.display = 'block';
        ph.style.display = 'none';
      } else if (isSkill) {
        img.style.display = 'none';
        ph.style.display = 'flex';
        ph.querySelector('.icon').textContent = skillIcon(staged.mode);
        this._q('placeholderText').textContent = `${staged.name} — fresh content will render when sent`;
      }

      const btnSend = this._q('btnSend');
      btnSend.textContent = '⬆ Send to Frame';
      btnSend.disabled = false;
      this._q('btnCancel').disabled = false;
      this._q('actions').style.display = 'flex';
      this._updateBadge();
      this._refreshToolbar();
    }

    _unstage() {
      this._staged = null;
      if (this._stagedPreviewUrl) {
        URL.revokeObjectURL(this._stagedPreviewUrl);
        this._stagedPreviewUrl = null;
      }
      const fi = this._q('fileInput');
      if (fi) fi.value = '';
      this._q('actions').style.display = 'none';
      const ph = this._q('placeholder');
      ph.querySelector('.icon').textContent = '🖼';
      this._q('placeholderText').textContent = 'Nothing sent yet — click to choose a photo';
      this._hideFeedback();
      // Repaint the confirmed on-frame image.
      this._mediaSourceUrl = null;
      this._frameThumbEtag = null;
      this._showPlaceholder();
      this._renderMedia();
      this._refreshToolbar();
    }

    async _send() {
      const staged = this._staged;
      const frame = this._frame;
      if (!staged || !this._hass) return;
      if (!frame) {
        this._showFeedback('error', 'Frame not found — check the card configuration.');
        return;
      }
      if (staged.kind !== 'skill' && !frame.battery_entity_id) {
        this._showFeedback('error', 'This frame has no battery sensor entity yet — try reloading the integration.');
        return;
      }

      const btnSend = this._q('btnSend');
      const btnCancel = this._q('btnCancel');
      btnSend.textContent = '⏳ Sending…';
      btnSend.disabled = true;
      btnCancel.disabled = true;

      try {
        let result;
        if (staged.kind === 'file') {
          const form = new FormData();
          form.append('entity_id', frame.battery_entity_id);
          form.append('image', staged.file);
          const resp = await fetch('/api/digital_frames/send_image', {
            method: 'POST', headers: this._authHeaders(), body: form,
          });
          result = await resp.json().catch(() => ({}));
          result._httpOk = resp.ok;
        } else if (staged.kind === 'image') {
          const form = new FormData();
          form.append('entity_id', frame.battery_entity_id);
          form.append('image_id', staged.imageId);
          const resp = await fetch('/api/digital_frames/library/send', {
            method: 'POST', headers: this._authHeaders(), body: form,
          });
          result = await resp.json().catch(() => ({}));
          result._httpOk = resp.ok;
        } else {
          const resp = await fetch(`/api/digital_frames/skills/${encodeURIComponent(staged.skillId)}/send`, {
            method: 'POST',
            headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ entry_id: frame.entry_id }),
          });
          const data = await resp.json().catch(() => ({}));
          const one = (data.results && data.results[0]) || {};
          result = { success: data.success, queued: one.queued, message: one.message, _httpOk: resp.ok };
        }

        if (result._httpOk && result.success) {
          this._showFeedback('success', '✓ Sent to frame!');
          setTimeout(() => {
            // Same staleness guard as _cropSaveSend() below: don't clobber
            // a pick staged after this send started.
            if (this._staged === staged) {
              this._unstage();
              this._refreshFrames(true);
            }
          }, 1200);
        } else if (result.queued) {
          this._showFeedback('success', '⏳ Frame is asleep — queued, will send on wake.');
          setTimeout(() => {
            if (this._staged === staged) {
              this._unstage();
              this._refreshFrames(true);
            }
          }, 1500);
        } else {
          throw new Error(result.message || `HTTP error`);
        }
      } catch (err) {
        this._showFeedback('error', `Failed: ${err.message}`);
        btnSend.textContent = '⬆ Send to Frame';
        btnSend.disabled = false;
        btnCancel.disabled = false;
      }
    }

    // ------------------------------------------------------------------ //
    // Orientation
    // ------------------------------------------------------------------ //

    async _setOrientation(orientation) {
      const frame = this._frame;
      if (!frame || !frame.orientation_entity_id || !this._hass) return;
      try {
        await this._hass.callService('select', 'select_option', {
          entity_id: frame.orientation_entity_id,
          option: orientation === 'portrait' ? 'Portrait' : 'Landscape',
        });
        frame.orientation = orientation;
        this._refreshFooter();
        this._showFeedback('success', `Orientation set to ${orientation} — applies to the next image sent.`);
        setTimeout(() => this._hideFeedback(), 3500);
        // Effective width/height flip -- refetch for the new render spec.
        setTimeout(() => this._refreshFrames(true), 1500);
      } catch (err) {
        this._showFeedback('error', `Couldn't change orientation: ${err.message}`);
      }
    }

    // ------------------------------------------------------------------ //
    // Crop editor
    // ------------------------------------------------------------------ //

    async _openCrop() {
      const frame = this._frame;
      const imageId = this._cropTargetImageId();
      if (!frame || !imageId) return;

      this._crop = {
        imageId,
        targetW: frame.width,
        targetH: frame.height,
        naturalW: 0,
        naturalH: 0,
        cropBox: null,
        record: null,
      };
      const overlay = this._q('cropOverlay');
      overlay.style.display = 'flex';
      this._q('cropTitle').textContent = `Adjust crop — ${this._config.name || frame.title}`;
      this._q('cropBox').style.display = 'none';
      this._hideCropFb();

      // Keep the box glued to the letterboxed image if the viewport
      // changes while the editor is open (phone rotation, window resize).
      if (!this._onCropResize) this._onCropResize = () => this._renderCropBox();
      window.addEventListener('resize', this._onCropResize);

      try {
        // Full library record (for any saved crop) + the original pixels.
        const [listResp, imgResp] = await Promise.all([
          fetch('/api/digital_frames/library/list', { headers: this._authHeaders() }),
          fetch(`/api/digital_frames/library/image/${imageId}`, { headers: this._authHeaders() }),
        ]);
        if (!imgResp.ok) throw new Error(`HTTP ${imgResp.status}`);
        const listData = await listResp.json().catch(() => ({}));
        const record = (listData.images || []).find((i) => i.image_id === imageId) || {};
        const blob = await imgResp.blob();
        if (!this._crop || this._crop.imageId !== imageId) return; // closed mid-load

        if (this._cropImgUrl) URL.revokeObjectURL(this._cropImgUrl);
        this._cropImgUrl = URL.createObjectURL(blob);
        const img = this._q('cropImg');
        img.src = this._cropImgUrl;
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = () => reject(new Error('image decode failed'));
        });
        if (!this._crop || this._crop.imageId !== imageId) return;

        this._crop.record = record;
        this._crop.naturalW = img.naturalWidth;
        this._crop.naturalH = img.naturalHeight;

        // Saved crop for this exact resolution, else the orientation
        // fallback, else the automatic centered cover box -- the same
        // precedence async_get_bin_for_send applies when rendering.
        const crops = record.crops || {};
        const key = `${frame.width}x${frame.height}`;
        const orientKey = frame.width < frame.height ? 'portrait' : 'landscape';
        const saved = crops[key] || crops[orientKey];
        this._crop.cropBox = saved
          ? saved.slice()
          : computeCoverBox(img.naturalWidth, img.naturalHeight, frame.width, frame.height);
        this._renderCropBox();
      } catch (err) {
        this._showCropFb('error', `Couldn't load image: ${err.message}`);
      }
    }

    _closeCrop() {
      this._q('cropOverlay').style.display = 'none';
      if (this._cropImgUrl) {
        URL.revokeObjectURL(this._cropImgUrl);
        this._cropImgUrl = null;
      }
      this._q('cropImg').removeAttribute('src');
      this._crop = null;
      this._cropDrag = null;
      window.removeEventListener('pointermove', this._onCropMove);
      window.removeEventListener('pointerup', this._onCropUp);
      if (this._onCropResize) window.removeEventListener('resize', this._onCropResize);
    }

    // The on-screen rect the image actually occupies inside the stage
    // (object-fit: contain letterboxing).
    _cropImageRect() {
      const stage = this._q('cropStage');
      const stageW = stage.clientWidth;
      const stageH = stage.clientHeight;
      const { naturalW, naturalH } = this._crop;
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

    _renderCropBox() {
      const crop = this._crop;
      if (!crop || !crop.cropBox) return;
      const { offsetX, offsetY, renderedW, renderedH } = this._cropImageRect();
      const el = this._q('cropBox');
      const [x0, y0, x1, y1] = crop.cropBox;
      el.style.display = 'block';
      el.style.left = `${offsetX + x0 * renderedW}px`;
      el.style.top = `${offsetY + y0 * renderedH}px`;
      el.style.width = `${(x1 - x0) * renderedW}px`;
      el.style.height = `${(y1 - y0) * renderedH}px`;
    }

    _cropBeginDrag(e, mode, handle) {
      if (!this._crop || !this._crop.cropBox) return;
      e.preventDefault();
      e.stopPropagation();
      this._cropDrag = {
        mode,
        handle,
        startClientX: e.clientX,
        startClientY: e.clientY,
        startBox: this._crop.cropBox.slice(),
        imgRect: this._cropImageRect(),
      };
      window.addEventListener('pointermove', this._onCropMove);
      window.addEventListener('pointerup', this._onCropUp);
    }

    _onCropMove(e) {
      const drag = this._cropDrag;
      if (!drag || !this._crop) return;
      const { renderedW, renderedH } = drag.imgRect;
      const dxNorm = (e.clientX - drag.startClientX) / renderedW;
      const dyNorm = (e.clientY - drag.startClientY) / renderedH;
      const [sx0, sy0, sx1, sy1] = drag.startBox;

      let box;
      if (drag.mode === 'move') {
        const w = sx1 - sx0, h = sy1 - sy0;
        const x0 = Math.min(Math.max(sx0 + dxNorm, 0), 1 - w);
        const y0 = Math.min(Math.max(sy0 + dyNorm, 0), 1 - h);
        box = [x0, y0, x0 + w, y0 + h];
      } else {
        const ar = this._crop.targetW / this._crop.targetH;
        box = resizeBox(drag.startBox, drag.handle, dxNorm, dyNorm, ar);
      }
      this._crop.cropBox = box;
      this._renderCropBox();
    }

    _onCropUp() {
      this._cropDrag = null;
      window.removeEventListener('pointermove', this._onCropMove);
      window.removeEventListener('pointerup', this._onCropUp);
    }

    async _cropSaveSend() {
      const crop = this._crop;
      const frame = this._frame;
      const staged = this._staged;
      if (!crop || !crop.cropBox || !frame) return;
      const btn = this._q('cropSaveSend');
      const prev = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Saving…';
      try {
        const saveResp = await fetch('/api/digital_frames/library/crop', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_id: crop.imageId,
            width: crop.targetW,
            height: crop.targetH,
            crop_box: crop.cropBox,
          }),
        });
        const saveResult = await saveResp.json().catch(() => ({}));
        if (!saveResp.ok || !saveResult.success) {
          throw new Error(saveResult.message || `HTTP ${saveResp.status}`);
        }

        btn.textContent = '⏳ Sending…';
        const form = new FormData();
        form.append('entity_id', frame.battery_entity_id);
        form.append('image_id', crop.imageId);
        const sendResp = await fetch('/api/digital_frames/library/send', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const sendResult = await sendResp.json().catch(() => ({}));
        if (sendResult.queued) {
          this._showCropFb('success', '✓ Crop saved. ⏳ Frame is asleep — queued, will send on wake.');
        } else if (!sendResp.ok || !sendResult.success) {
          throw new Error(sendResult.message || `HTTP ${sendResp.status}`);
        } else {
          this._showCropFb('success', '✓ Crop saved and sent to the frame!');
        }
        setTimeout(() => {
          this._closeCrop();
          // Crop can target a staged-but-unsent pick (_cropTargetImageId);
          // this send just confirmed it on the frame, so leaving _staged
          // set afterward left the Send/Cancel bar and PREVIEW badge stuck
          // showing stale state indefinitely -- mirrors the same
          // unstage-after-confirmed-send done in _send() above. But only
          // if _staged is still the same pick this crop session started
          // with -- the user may have closed the crop overlay (cropClose
          // isn't disabled during save/send) and staged something else
          // while this was in flight, and that newer pick must not be
          // silently discarded.
          if (this._staged === staged) {
            this._unstage();
            this._refreshFrames(true);
          }
        }, 1400);
      } catch (err) {
        this._showCropFb('error', `Failed: ${err.message}`);
      }
      btn.disabled = false;
      btn.textContent = prev;
    }

    async _cropReset() {
      const crop = this._crop;
      if (!crop) return;
      try {
        const resp = await fetch('/api/digital_frames/library/crop', {
          method: 'DELETE',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_id: crop.imageId,
            width: crop.targetW,
            height: crop.targetH,
          }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || `HTTP ${resp.status}`);
        }
        crop.record = result.image || crop.record;
        crop.cropBox = computeCoverBox(crop.naturalW, crop.naturalH, crop.targetW, crop.targetH);
        this._renderCropBox();
        this._showCropFb('success', 'Reverted to the automatic framing — Save & Send to apply it.');
      } catch (err) {
        this._showCropFb('error', `Couldn't reset: ${err.message}`);
      }
    }

    _showCropFb(type, msg) {
      const el = this._q('cropFb');
      el.className = `crop-fb ${type}`;
      el.textContent = msg;
      el.style.display = 'block';
    }

    _hideCropFb() {
      const el = this._q('cropFb');
      if (el) el.style.display = 'none';
    }

    // ------------------------------------------------------------------ //
    // Feedback
    // ------------------------------------------------------------------ //

    _showFeedback(type, msg) {
      const el = this._q('feedback');
      el.className = `feedback ${type}`;
      el.textContent = msg;
      el.style.display = 'block';
    }

    _hideFeedback() {
      const el = this._q('feedback');
      if (el) el.style.display = 'none';
    }
  }

  customElements.define('digital-frames-card', DigitalFramesCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'digital-frames-card',
    name: 'Digital Frames Card',
    description: 'See what\'s on a Fraimic e-ink frame and manage it: send photos or daily content, change orientation, adjust cropping.',
    preview: true,
    documentationURL: 'https://github.com/dsackr/ha-digital-frames',
  });

  console.info(
    '%c FRAIMIC-CARD %c v' + CARD_VERSION + ' ',
    'background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px 0 0 3px;font-weight:600',
    'background:#1e293b;color:#fff;padding:2px 6px;border-radius:0 3px 3px 0',
  );
})();
