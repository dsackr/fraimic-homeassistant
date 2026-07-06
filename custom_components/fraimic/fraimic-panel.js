/**
 * Fraimic Panel
 * Sidebar panel that auto-discovers all Fraimic frames and lets you send
 * images to any of them — no manual card configuration required.
 */

(function () {
  'use strict';

  const PANEL_VERSION = '0.10.2';

  // Mirrors library.py's DEFAULT_ALBUM -- every photo belongs to this album
  // unless/until it's reorganized elsewhere; can't be renamed or deleted.
  const DEFAULT_ALBUM = 'Images';

  // Mirrors const.py's SCENE_PACK_RAW_BASE -- scene pack cover art is public
  // content, so the browser fetches it directly instead of proxying through
  // a Fraimic endpoint.
  const SCENE_PACK_RAW_BASE = 'https://raw.githubusercontent.com/dsackr/frame-addons/main';

  // Mirrors the "category" values scripts/build_scene_pack.py writes into
  // each pack's index.json entry -- the Add-ons tab browses packs grouped
  // into these tiles before drilling into a flat pack grid.
  const PACK_CATEGORIES = {
    art: { label: 'Art' },
    seasonal: { label: 'Seasonal & Holiday' },
    widgets: { label: 'Active Add-ons' },
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

    /* ---- tab bar ---- */
    .tab-bar {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 4px;
      background: var(--card-background-color, #fff);
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
      margin: -24px -24px 20px;
      padding: 0 24px;
    }
    .tab-btn {
      flex: 0 0 auto;
      padding: 12px 20px;
      border: none;
      background: transparent;
      font-size: 14px;
      font-weight: 500;
      color: var(--secondary-text-color);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: color .15s ease, border-color .15s ease;
    }
    .tab-btn:hover:not(.active) { color: var(--primary-text-color); }
    .tab-btn.active {
      color: var(--primary-color, #3b82f6);
      border-bottom-color: var(--primary-color, #3b82f6);
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
    }

    /* Full-width group labels inside a .grid/.lib-grid -- see
       _buildSectionHeader/_buildSectionEmpty. */
    .section-header {
      grid-column: 1 / -1;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: var(--secondary-text-color);
      padding-bottom: 4px;
      margin-top: 4px;
      border-bottom: 1px solid var(--divider-color, #e2e8f0);
    }
    .section-header:first-child { margin-top: 0; }
    .section-empty {
      grid-column: 1 / -1;
      text-align: center;
      padding: 16px 8px 24px;
      color: var(--secondary-text-color);
    }
    .section-empty-icon { font-size: 24px; margin-bottom: 4px; }
    .section-empty-title { font-size: 13px; font-weight: 600; color: var(--primary-text-color); }
    .section-empty-body { font-size: 12px; max-width: 420px; margin: 4px auto 0; }

    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      padding: 20px;
      box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.1));
    }
    .card.deep-link-highlight {
      outline: 3px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
      transition: outline-color 0.3s ease;
    }
    .card.frame-tile {
      padding: 10px;
    }

    /* ---- frame tile ---- */
    .frame-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .frame-icon {
      width: 32px; height: 32px;
      border-radius: 8px;
      background: var(--primary-color, #3b82f6);
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      overflow: hidden;
    }
    .frame-icon img {
      width: 100%; height: 100%;
      object-fit: cover;
    }
    .frame-orientation-select {
      flex: 0 0 auto;
      max-width: 88px;
      font-size: 10px;
      color: var(--secondary-text-color);
      background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color, #e2e8f0);
      border-radius: 6px;
      padding: 2px 4px;
    }
    .frame-host-link {
      flex: 0 0 auto;
      width: 26px; height: 26px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      color: var(--secondary-text-color);
      text-decoration: none;
      transition: background .15s ease, color .15s ease;
    }
    .frame-host-link:hover {
      background: var(--secondary-background-color, #e2e8f0);
      color: var(--primary-text-color);
    }
    .frame-action-btn {
      flex: 0 0 auto;
      width: 26px; height: 26px;
      border-radius: 50%;
      display: inline-flex; align-items: center; justify-content: center;
      color: var(--secondary-text-color);
      background: transparent;
      border: none;
      cursor: pointer;
      padding: 0;
      transition: background .15s ease, color .15s ease;
    }
    .frame-action-btn:hover {
      background: var(--secondary-background-color, #e2e8f0);
      color: var(--primary-text-color);
    }
    .frame-action-btn.loading svg {
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .frame-meta { flex: 1; min-width: 0; }
    .frame-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--primary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .frame-status {
      font-size: 11px;
      color: var(--secondary-text-color);
      margin-top: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .frame-origin-clone {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: var(--warning-color, #b45309);
    }
    .dot-on  { color: var(--success-color,  #16a34a); }
    .dot-off { color: var(--error-color,    #dc2626); }
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
      padding: 8px 12px;
      border-radius: 8px;
      border-left: 3px solid transparent;
      font-size: 12px;
      line-height: 1.4;
      width: fit-content;
      max-width: 100%;
      box-sizing: border-box;
    }
    .feedback.ok {
      background: rgba(22,163,74,.08);
      border-left-color: var(--success-color, #16a34a);
      color: var(--success-color, #15803d);
    }
    .feedback.err {
      background: rgba(220,38,38,.08);
      border-left-color: var(--error-color, #dc2626);
      color: var(--error-color, #b91c1c);
    }

    /* ---- empty state ---- */
    .empty {
      text-align: center;
      padding: 56px 24px;
      color: var(--secondary-text-color);
    }
    .empty-icon {
      width: 56px;
      height: 56px;
      margin: 0 auto 16px;
      border-radius: 50%;
      background: var(--secondary-background-color, #e2e8f0);
      color: var(--secondary-text-color);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
    }
    .empty h2 { margin: 0 0 8px; font-size: 16px; font-weight: 600; color: var(--primary-text-color); }
    .empty p  { margin: 0 auto; max-width: 420px; font-size: 13px; line-height: 1.6; }

    /* ---- library ---- */
    .lib-toolbar {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .lib-toolbar-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-left: auto;
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
      gap: 20px;
    }
    .lib-thumb {
      position: relative;
      border-radius: 8px;
      overflow: hidden;
      background: var(--secondary-background-color, #f1f5f9);
      margin-bottom: 10px;
      height: 160px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .lib-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .lib-card .btns select { flex: 1; }
    .lib-card .btns + .btns { margin-top: 6px; }

    /* ---- library multi-select ---- */
    .lib-select-check {
      position: absolute;
      top: 8px;
      right: 8px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: rgba(15,23,42,.55);
      color: #fff;
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
    }
    .lib-card.selected .lib-select-check {
      opacity: 1;
      background: var(--primary-color, #3b82f6);
    }
    .lib-card.selectable { cursor: pointer; }
    .lib-card.selected { outline: 2px solid var(--primary-color, #3b82f6); outline-offset: 2px; }
    .lib-select-count {
      font-size: 13px;
      color: var(--secondary-text-color);
    }

    /* ---- albums ---- */
    .lib-breadcrumb {
      display: none;
      align-items: center;
      gap: 10px;
      margin-bottom: 16px;
    }
    .lib-breadcrumb button {
      flex: 0 0 auto;
      padding: 6px 12px;
      border-radius: 8px;
      background: var(--secondary-background-color, #e2e8f0);
      color: var(--primary-text-color);
      border: none;
      font-size: 13px;
      cursor: pointer;
    }
    .lib-breadcrumb-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--primary-text-color);
    }
    .album-tile { cursor: pointer; }
    .album-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--primary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      cursor: pointer;
    }
    .album-count {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 2px;
    }
    .album-tile-actions {
      display: flex;
      gap: 6px;
      margin-top: 10px;
    }
    .album-tile-actions button {
      flex: 1;
      padding: 6px;
      font-size: 12px;
    }

    /* ---- simple modal (upload / album picker) ---- */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, .5);
      z-index: 1100;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
      box-sizing: border-box;
    }
    .modal-box {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      padding: 20px;
      width: 100%;
      max-width: 380px;
      max-height: 80vh;
      overflow-y: auto;
      box-shadow: 0 10px 40px rgba(0,0,0,.3);
      box-sizing: border-box;
    }
    .modal-box h3 {
      margin: 0 0 14px;
      font-size: 16px;
      color: var(--primary-text-color);
    }
    .modal-row { margin-bottom: 12px; }
    .modal-row label {
      display: block;
      font-size: 13px;
      color: var(--secondary-text-color);
      margin-bottom: 4px;
    }
    .modal-row select, .modal-row input[type="text"] {
      width: 100%;
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid var(--divider-color, rgba(0,0,0,.15));
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-size: 13px;
      box-sizing: border-box;
    }
    #upload-modal-files {
      display: block;
      width: 100%;
      font-size: 12px;
      color: var(--primary-text-color);
    }
    .modal-file-summary {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 6px;
    }
    .modal-actions { display: flex; gap: 8px; margin-top: 16px; }
    .album-checklist {
      max-height: 220px;
      overflow-y: auto;
      margin-bottom: 12px;
    }
    .album-checklist label {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 0;
      font-size: 13px;
      color: var(--primary-text-color);
    }

    /* ---- image picker (Create Album) ---- */
    .image-picker-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
      gap: 8px;
      max-height: 280px;
      overflow-y: auto;
      padding: 4px;
      border: 1px solid var(--divider-color, rgba(0,0,0,.12));
      border-radius: 8px;
    }
    .image-picker-cell {
      position: relative;
      height: 70px;
      border-radius: 6px;
      overflow: hidden;
      cursor: pointer;
      border: 2px solid transparent;
    }
    .image-picker-thumb {
      position: absolute;
      inset: 0;
      background: var(--secondary-background-color, #f1f5f9);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
    }
    .image-picker-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .image-picker-cell.selected {
      border-color: var(--primary-color, #3b82f6);
    }
    .image-picker-check {
      position: absolute;
      top: 3px;
      right: 3px;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: rgba(15,23,42,.55);
      color: #fff;
      font-size: 11px;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
    }
    .image-picker-cell.selected .image-picker-check {
      opacity: 1;
      background: var(--primary-color, #3b82f6);
    }

    /* ---- scenes ---- */
    .scene-card-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--primary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .scene-card-summary {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 3px;
    }

    /* ---- frames sub-nav (Status / Walls) ---- */
    .frames-subnav {
      display: flex;
      gap: 4px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
    }
    .subnav-btn {
      flex: 0 0 auto;
      padding: 8px 14px;
      border: none;
      background: transparent;
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: color .15s ease, border-color .15s ease;
    }
    .subnav-btn:hover:not(.active) { color: var(--primary-text-color); }
    .subnav-btn.active {
      color: var(--primary-color, #3b82f6);
      border-bottom-color: var(--primary-color, #3b82f6);
    }
    .frames-sub { display: none; }
    .frames-sub.active { display: block; }

    /* ---- walls ---- */
    .wall-layout-row {
      display: flex;
      gap: 16px;
      align-items: flex-start;
    }
    .wall-palette {
      flex: 0 0 160px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 8px;
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      min-height: 400px;
      box-sizing: border-box;
    }
    .wall-palette-item {
      padding: 8px 10px;
      border-radius: 6px;
      background: var(--secondary-background-color, #f1f5f9);
      color: var(--primary-text-color);
      cursor: grab;
      font-size: 12px;
      touch-action: none;
    }
    .wall-canvas {
      position: relative;
      flex: 1 1 auto;
      min-height: 400px;
      background-color: var(--secondary-background-color, #f8fafc);
      background-image:
        linear-gradient(to right, rgba(0,0,0,.06) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(0,0,0,.06) 1px, transparent 1px);
      background-size: 20px 20px;
      border-radius: var(--ha-card-border-radius, 12px);
      border: 1px dashed var(--divider-color, rgba(0,0,0,.2));
      overflow: auto;
      box-sizing: border-box;
    }
    .wall-tile {
      position: absolute;
      border-radius: 4px;
      overflow: hidden;
      background: var(--card-background-color, #fff);
      box-shadow: 0 1px 5px rgba(0,0,0,.3);
      cursor: grab;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: var(--secondary-text-color);
      text-align: center;
      padding: 2px;
      box-sizing: border-box;
      touch-action: none;
    }
    .wall-tile.dragging { opacity: .5; z-index: 10; cursor: grabbing; }
    .wall-tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .wall-drag-ghost {
      position: fixed;
      pointer-events: none;
      z-index: 1200;
      opacity: .85;
      border-radius: 4px;
      background: var(--card-background-color, #fff);
      box-shadow: 0 4px 16px rgba(0,0,0,.35);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: var(--primary-text-color);
      text-align: center;
      padding: 2px;
      box-sizing: border-box;
    }

    /* ---- wall image picker: draggable floating panel, not a centered
       modal-overlay -- see the HTML comment above its markup. The overlay
       itself is transparent (the wall stays visible through it) but DOES
       catch pointer events -- clicking it (not the box) closes the picker,
       same "click outside to dismiss" behavior a normal modal backdrop
       gives you, just without darkening the view. ---- */
    .wall-picker-overlay {
      position: fixed;
      inset: 0;
      z-index: 1100;
      display: none;
      background: transparent;
    }
    .wall-picker-box {
      position: absolute;
      left: 50%;
      top: 72px;
      transform: translateX(-50%);
      pointer-events: auto;
      width: 380px;
      max-width: calc(100vw - 32px);
      max-height: calc(100vh - 96px);
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: 0 10px 40px rgba(0,0,0,.35);
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .wall-picker-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 10px 10px 16px;
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
      cursor: grab;
      touch-action: none;
      flex: 0 0 auto;
    }
    .wall-picker-header.dragging { cursor: grabbing; }
    .wall-picker-header h3 { margin: 0; font-size: 15px; color: var(--primary-text-color); }
    .wall-picker-body {
      padding: 16px;
      overflow-y: auto;
      flex: 1 1 auto;
    }
    .wall-lock-hint {
      font-size: 12px;
      color: var(--secondary-text-color);
      background: var(--secondary-background-color, #f1f5f9);
      border-radius: 6px;
      padding: 8px 10px;
      margin-top: 10px;
      line-height: 1.5;
    }
    .wall-lock-hint.warn {
      color: var(--warning-color, #b45309);
      background: rgba(180, 83, 9, .1);
    }

    /* ---- scene packs ---- */
    .pack-cover {
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: cover;
      border-radius: 8px;
      margin-bottom: 10px;
      background: var(--secondary-background-color, #e2e8f0);
      cursor: pointer;
    }
    .pack-desc {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 3px;
    }
    .badge-installed {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(22,163,74,.12);
      color: var(--success-color, #16a34a);
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }

    /* ---- scene pack categories ---- */
    .addons-crumb {
      display: none;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
    }
    .addons-crumb-label {
      font-size: 14px;
      font-weight: 600;
      color: var(--primary-text-color);
    }
    .category-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 20px;
    }
    .category-tile {
      position: relative;
      padding: 0;
      overflow: hidden;
      cursor: pointer;
      aspect-ratio: 16 / 10;
      transition: transform .15s ease, box-shadow .15s ease;
    }
    .category-tile:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(0,0,0,.18);
    }
    .category-tile-cover {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .category-tile-overlay {
      position: absolute;
      inset: auto 0 0 0;
      padding: 16px;
      background: linear-gradient(transparent, rgba(0,0,0,.75));
      color: #fff;
    }
    .category-tile-title {
      font-size: 18px;
      font-weight: 700;
    }
    .category-tile-summary {
      font-size: 12px;
      opacity: .9;
      margin-top: 2px;
    }

    /* ---- scene pack preview (read-only image gallery) ---- */
    .pack-preview-nav {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 44px;
      height: 44px;
      border-radius: 50%;
      border: none;
      background: rgba(255,255,255,.12);
      color: #fff;
      font-size: 24px;
      cursor: pointer;
      z-index: 1;
    }
    .pack-preview-nav:hover { background: rgba(255,255,255,.22); }
    .pack-preview-prev { left: 8px; }
    .pack-preview-next { right: 8px; }
    .pack-preview-counter {
      margin-left: auto;
      font-size: 13px;
      opacity: .75;
      flex: 0 0 auto;
    }
    .pack-preview-caption {
      padding: 10px 18px 18px;
      font-size: 13px;
      color: rgba(255,255,255,.85);
      text-align: center;
      flex: 0 0 auto;
    }
    .scene-mapping-row {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 0;
    }
    .scene-mapping-thumb {
      width: 40px;
      height: 40px;
      border-radius: 6px;
      overflow: hidden;
      background: var(--secondary-background-color, #f1f5f9);
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      font-size: 16px;
    }
    .scene-mapping-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .scene-mapping-frame {
      flex: 1;
      min-width: 0;
      font-size: 13px;
      color: var(--primary-text-color);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .scene-mapping-row select { flex: 1.4; min-width: 0; }

    /* -- crop editor (aspect follows the selected frame's orientation) ---- */
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
    .editor-hint {
      font-size: 12px;
      opacity: .65;
      line-height: 1.4;
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

      this._library      = [];        // [{ image_id, filename, content_type, resolutions, albums }]
      this._backend       = 'local';  // active library storage backend

      // image_id → blob: URL for the ?thumb= endpoint variant. One cache
      // shared by every grid (library, albums, scenes, walls, pickers),
      // kept for the panel's lifetime so re-renders reuse the already-
      // downloaded thumbnail instead of refetching; entries are evicted
      // only when the image itself is deleted (see _evictThumb).
      this._thumbUrls    = {};
      this._thumbFetches = {};        // image_id → in-flight fetch promise (dedupes concurrent tiles)

      // Uncached thumbnails load lazily: tiles register with this observer
      // and only fetch once they scroll near the viewport, through a small
      // concurrency-capped queue -- so a big grid doesn't fire one fetch
      // per photo up front, and grids in hidden tabs (display:none never
      // intersects) cost nothing until the tab is opened. Cache hits skip
      // all of this and paint synchronously (see _loadThumbnail).
      this._thumbQueue  = [];   // [{ imageId, container }] waiting for a fetch slot
      this._thumbActive = 0;    // thumbnail fetches currently in flight
      this._thumbObserver = this._makeThumbObserver();

      // Every window/document-level listener is registered with this
      // controller's signal so disconnecting the panel (navigating to
      // another HA panel) severs them all at once -- without this, each
      // visit left behind global listeners closing over the whole detached
      // shadow tree. See disconnectedCallback/_dispose/_revive.
      this._abort = new AbortController();
      this._disposed = false;      // true after _dispose ran (detached for real)
      this._disposeTimer = null;   // pending deferred dispose, cancellable by a same-tick reattach

      this._albums        = [];       // [{ name, count, cover_image_id }]
      this._currentAlbum  = null;     // null = album folder view; a name = viewing that album
      this._albumPickerImage = null;  // image currently open in the "Add to Album" picker
      this._albumCreateSelected = new Set();  // image_ids selected in the "Create Album" picker

      this._librarySelectMode = false;  // true = photo grid is in multi-select-for-delete mode
      this._librarySelected   = new Set();  // image_ids selected while in that mode

      this._packerOverride = null;         // 'legacy' | 'fast' | null -- see ?packer in _init
      this._packTestSelectedImage = null;  // image_id picked in the ?packtest modal

      this._scenes        = [];       // [{ scene_id, name, mappings: { entry_id: image_id }, source }]
      this._sceneEditorId  = null;    // scene_id being edited, or null when creating a new one

      this._scenePacks    = [];       // [{ id, name, description, category, license, cover, images, installed, scene_created }]
      this._activeTab     = 'library'; // 'library' | 'frames' | 'scenes' | 'addons'
      this._packCategory  = null;     // null = category-tile view; otherwise the category id being browsed
      this._packPreview   = null;     // { pack, index } while the read-only image gallery is open, else null

      this._framesSub = 'status';     // 'status' | 'walls' -- sub-view within the Frames tab
      this._walls          = [];      // [{ wall_id, name, placements: { entry_id: {x, y} } }]
      this._activeWallId   = null;    // wall_id currently open in the Walls sub-view
      this._wallPlacements = {};      // working copy of the active wall's placements while editing layout
      this._wallDrag        = null;   // in-progress palette/tile pointer drag, or null
      this._wallActiveSceneId = null;    // scene_id loaded for preview on this wall, or null
      this._wallPendingMappings = {};    // entry_id -> image_id ('' = explicitly cleared) touched this session,
                                          // overlaid on the active scene's own mappings -- see _wallEffectiveMapping
      this._wallPendingPickAlbum = {};   // entry_id -> the album filter value active in the picker when that
                                          // pending pick was made ('' = "All Photos") -- see _wallSceneAlbumLock
      this._wallImagePickerEntryId = null; // entry_id whose "choose an image" picker is open, or null
      this._wallImagePickerToken = 0;      // incremented per open -- lets a stale fetch detect it's superseded
      this._onWallPointerMove = this._onWallPointerMove.bind(this);
      this._onWallPointerUp   = this._onWallPointerUp.bind(this);

      this._editorState = null;   // active crop-editor session, or null when closed
      this._editorDrag  = null;   // in-progress pointer drag, or null
      this._editorRenderRaf = null; // pending crop-box render frame, or null
      this._editorImgUrl = null;  // blob: URL for the editor's full-size image
      this._onEditorPointerMove = this._onEditorPointerMove.bind(this);
      this._onEditorPointerUp   = this._onEditorPointerUp.bind(this);
    }

    // -----------------------------------------------------------------------
    // Element lifecycle: sever global listeners + release blob memory when
    // the panel leaves the DOM (HA navigations), and recover if it returns.
    // -----------------------------------------------------------------------

    _makeThumbObserver() {
      if (typeof IntersectionObserver === 'undefined') return null;
      return new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          this._thumbObserver.unobserve(entry.target);
          const imageId = entry.target._fraimicThumbId;
          if (imageId) this._enqueueThumbFetch(imageId, entry.target);
        }
      }, { rootMargin: '200px' });
    }

    disconnectedCallback() {
      // Defer: a same-tick detach/reattach (the surrounding app moving
      // nodes) must not tear anything down. connectedCallback cancels this.
      this._disposeTimer = setTimeout(() => {
        this._disposeTimer = null;
        this._dispose();
      }, 0);
    }

    connectedCallback() {
      if (this._disposeTimer) {
        clearTimeout(this._disposeTimer);
        this._disposeTimer = null;
      }
      if (this._disposed) this._revive();
    }

    _dispose() {
      this._disposed = true;
      this._abort.abort();
      if (this._thumbObserver) this._thumbObserver.disconnect();
      if (this._wallDrag) {
        if (this._wallDrag.ghost) this._wallDrag.ghost.remove();
        this._wallDrag = null;
      }
      this._editorDrag = null;
      // blob: URLs are registered on the document, not this element -- left
      // unrevoked they'd keep every thumbnail's bytes alive until a full
      // page reload, once per panel visit.
      for (const url of Object.values(this._thumbUrls)) URL.revokeObjectURL(url);
      this._thumbUrls = {};
      this._thumbFetches = {};
      this._thumbQueue = [];
      if (this._editorImgUrl) {
        URL.revokeObjectURL(this._editorImgUrl);
        this._editorImgUrl = null;
      }
    }

    // Defensive: today's HA recreates a custom panel element per visit, but
    // if this exact element ever re-enters the DOM, put it back in working
    // order instead of leaving dead listeners and revoked image URLs.
    _revive() {
      this._disposed = false;
      this._abort = new AbortController();
      this._thumbObserver = this._makeThumbObserver();
      this._addGlobalListeners();
      if (!this._loaded) return;
      // Grid <img>s still point at revoked blob: URLs -- re-render from
      // in-memory state so tiles re-register with the observer and refetch
      // (cheap: server-side disk thumbnail cache + browser HTTP cache).
      this._renderFrames();
      this._renderLibrary();
      this._renderScenes();
      this._renderScenePacks();
      this._renderWallsSubview();
    }

    // The three long-lived window/document listeners the panel needs.
    // Handler fields are created by _wireUploadModal/_wirePackPreview (run
    // once in _init); registration is separate so _revive can re-attach
    // them under the replacement AbortController.
    _addGlobalListeners() {
      const signal = this._abort.signal;
      if (this._sweepUploadInput) {
        window.addEventListener('focus', this._sweepUploadInput, { signal });
        document.addEventListener('visibilitychange', this._onDocVisibility, { signal });
      }
      if (this._onPackPreviewKeydown) {
        window.addEventListener('keydown', this._onPackPreviewKeydown, { signal });
      }
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
      // Hidden A/B test switches for the fast bin packer:
      //   /fraimic?packtest      -- guided one-image-two-frames test modal
      //                             (opens automatically once data loads)
      //   /fraimic?packer=fast   -- every Library "Send" carries this
      //   /fraimic?packer=legacy    packing-method override instead
      // Both make the backend bypass the .bin cache and convert fresh with
      // the requested packer, so the physical panels can be compared.
      let packTestRequested = false;
      try {
        const params = new URLSearchParams(window.location.search);
        packTestRequested = params.has('packtest');
        const packer = params.get('packer');
        this._packerOverride = (packer === 'fast' || packer === 'legacy') ? packer : null;
      } catch (err) {
        this._packerOverride = null;
      }
      if (this._packerOverride) {
        console.info(`[fraimic-panel] packer override active: ${this._packerOverride} (bin cache bypassed for library sends)`);
      }

      this._buildShell();
      this._wireNav();
      this._wireLibraryToolbar();
      this._wireEditor();
      this._wirePackPreview();
      this._wireUploadModal();
      this._wireAlbumPicker();
      this._wireAlbumCreate();
      this._wireSceneToolbar();
      this._wireSceneEditor();
      this._wireFramesSubnav();
      this._wireWallToolbar();
      this._wireWallImagePicker();
      this._wirePackTest();
      this._addGlobalListeners();
      // Fire every tab's data load concurrently and render each section as
      // its data lands -- these are independent endpoints, and awaiting
      // them serially made first paint wait on the sum of all round trips
      // (the old behavior). Render order below still preserves each
      // section's data dependencies (walls also needs frames, which is
      // awaited first).
      const framesP  = this._discoverFrames();
      const packsP   = this._loadScenePacks();
      const backendP = this._loadBackendSettings();
      const albumsP  = this._loadAlbums();
      const scenesP  = this._loadScenes();
      const wallsP   = this._loadWalls();

      await framesP;
      this._renderFrames();
      this._handleDeepLink();
      await Promise.all([backendP, albumsP]);
      this._renderLibrary();
      await scenesP;
      this._renderScenes();
      await wallsP;
      this._renderWallsSubview();
      await packsP;
      this._renderScenePacks();

      // Needs frames + albums, both awaited above.
      if (packTestRequested) this._openPackTestModal();
    }

    // Coming from a device page's "Visit" link (/fraimic?entry=<entry_id>):
    // jump straight to that frame's tile and highlight it.
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

      // Frames is no longer the default tab -- switch to it so the
      // highlighted card is actually visible.
      this._setTab('frames');
      card.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.el.classList.add('deep-link-highlight');
      setTimeout(() => card.el.classList.remove('deep-link-highlight'), 3000);
    }

    // -----------------------------------------------------------------------
    // Tab bar: Library / Frames / Scenes / Add-ons
    // -----------------------------------------------------------------------

    // Mirrors HA frontend's own navigate() helper: history.pushState must
    // happen BEFORE firing 'location-changed', since the app-router re-reads
    // window.location to decide what to render. Firing the event alone
    // (the old bug here) leaves the URL unchanged, so the router sees no
    // difference and does nothing.
    _navigate(path) {
      try {
        window.parent.history.pushState(null, '', path);
        window.parent.dispatchEvent(new CustomEvent('location-changed', {
          detail: { replace: false },
        }));
      } catch (err) {
        window.parent.location.href = path;
      }
    }

    _wireNav() {
      this.shadowRoot.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => this._setTab(btn.dataset.tab));
      });
      const addBtn = this.shadowRoot.getElementById('frame-add-btn');
      if (addBtn) {
        addBtn.addEventListener('click', () => {
          this._navigate('/config/integrations/dashboard/add?domain=fraimic');
        });
      }
      this._setTab('library');
    }

    _setTab(name) {
      this._activeTab = name;
      const root = this.shadowRoot;
      ['library', 'frames', 'scenes', 'addons'].forEach(tab => {
        const content = root.getElementById(`tab-${tab}`);
        const btn     = root.querySelector(`.tab-btn[data-tab="${tab}"]`);
        if (content) content.classList.toggle('active', tab === name);
        if (btn)     btn.classList.toggle('active', tab === name);
      });
    }

    _buildShell() {
      this.shadowRoot.innerHTML = `
        <style>${CSS}</style>

        <div class="tab-bar" id="tab-bar">
          <button class="tab-btn active" data-tab="library">Library</button>
          <button class="tab-btn" data-tab="frames">Frames</button>
          <button class="tab-btn" data-tab="scenes">Scenes</button>
          <button class="tab-btn" data-tab="addons">Add-ons</button>
        </div>

        <div class="tab-content active" id="tab-library">
        <div class="lib-toolbar">
          <div class="lib-backend">
            <label for="backend-select">Storage:</label>
            <select id="backend-select">
              <option value="local">Local (this Home Assistant)</option>
              <option value="google_drive">Google Drive</option>
              <option value="dropbox">Dropbox</option>
            </select>
          </div>
          <div class="lib-toolbar-actions">
            <button class="btn-primary" id="lib-upload-btn" style="flex:0 0 auto">⬆ Upload to Library</button>
            <button class="btn-ghost" id="album-create-btn" style="flex:0 0 auto">＋ Create Album</button>
            <button class="btn-ghost" id="lib-discover-btn" style="display:none;flex:0 0 auto"
              title="Adopt photos dropped into the Fraimic Library/inbox folder in Dropbox">🔍 Discover</button>
          </div>
        </div>
        <div class="backend-config" id="backend-config"></div>
        <div class="feedback" id="lib-fb"></div>
        <div class="lib-breadcrumb" id="lib-breadcrumb">
          <button id="lib-back-btn">← Albums</button>
          <span class="lib-breadcrumb-title" id="lib-breadcrumb-title"></span>
          <button class="btn-ghost" id="lib-select-toggle" style="margin-left:auto;flex:0 0 auto">☑ Select</button>
        </div>
        <div class="lib-toolbar" id="lib-select-toolbar" style="display:none">
          <span class="lib-select-count" id="lib-select-count">0 selected</span>
          <button class="btn-primary" id="lib-select-delete" style="flex:0 0 auto">🗑 Delete Selected</button>
          <button class="btn-ghost" id="lib-select-cancel" style="flex:0 0 auto">Cancel</button>
        </div>
        <div class="lib-grid" id="lib-grid">
          <div class="empty">
            <div class="empty-icon">⋯</div>
            <h2>Loading library…</h2>
          </div>
        </div>
        </div><!-- /tab-library -->

        <div class="tab-content" id="tab-frames">
        <div class="frames-subnav" id="frames-subnav">
          <button class="subnav-btn active" data-framesub="status">Status</button>
          <button class="subnav-btn" data-framesub="walls">Walls</button>
        </div>

        <div class="frames-sub active" id="frames-sub-status">
        <div class="lib-toolbar" style="justify-content:flex-end">
          <button class="btn-primary" id="frame-add-btn" style="flex:0 0 auto">＋ Add Frame</button>
        </div>
        <div class="grid" id="grid">
          <div class="empty">
            <div class="empty-icon">⋯</div>
            <h2>Discovering frames…</h2>
          </div>
        </div>
        </div><!-- /frames-sub-status -->

        <div class="frames-sub" id="frames-sub-walls">
        <div class="lib-toolbar">
          <div class="lib-backend">
            <label for="wall-select">Wall:</label>
            <select id="wall-select"><option value="">— Select a wall —</option></select>
          </div>
          <div class="lib-toolbar-actions">
            <button class="btn-primary" id="wall-new-btn" style="flex:0 0 auto">＋ New Wall</button>
            <button class="btn-ghost" id="wall-delete-btn" style="flex:0 0 auto;display:none">🗑 Delete Wall</button>
          </div>
        </div>
        <div class="feedback" id="wall-fb"></div>

        <div class="empty" id="wall-empty">
          <div class="empty-icon">▦</div>
          <h2>No wall selected</h2>
          <p>Create a wall to lay out a subset of your frames the way they're physically
             hung -- e.g. four frames on the living room wall -- then preview and edit
             scenes across them at once.</p>
        </div>

        <div id="wall-editor" style="display:none">
          <h3 style="margin:16px 0 6px;font-size:14px">Layout</h3>
          <p style="font-size:12px;color:var(--secondary-text-color);margin:0 0 10px">
            Drag a frame from the palette onto the wall, then drag a placed frame to
            reposition it. Positions snap to a grid.
          </p>
          <div class="wall-layout-row">
            <div class="wall-palette" id="wall-palette"></div>
            <div class="wall-canvas" id="wall-canvas"></div>
          </div>
          <div class="btns" style="margin-top:10px">
            <button class="btn-primary" id="wall-save-layout-btn">Save Layout</button>
          </div>

          <h3 style="margin:22px 0 6px;font-size:14px">Preview / Edit Scene</h3>
          <div class="modal-row" style="max-width:320px">
            <label for="wall-scene-select">Scene</label>
            <select id="wall-scene-select"><option value="">— None —</option></select>
          </div>
          <div class="wall-lock-hint" id="wall-lock-hint" style="display:none"></div>
          <div class="btns" style="margin-top:10px">
            <button class="btn-primary" id="wall-save-scene-btn">Save to Scene</button>
            <button class="btn-ghost" id="wall-save-new-scene-btn">Save As New Scene</button>
          </div>
          <div class="feedback" id="wall-scene-fb"></div>
        </div>
        </div><!-- /frames-sub-walls -->
        </div><!-- /tab-frames -->

        <div class="tab-content" id="tab-scenes">
        <div class="lib-toolbar" style="justify-content:flex-end">
          <button class="btn-primary" id="scene-new-btn" style="flex:0 0 auto">＋ New Scene</button>
        </div>
        <div class="feedback" id="scene-fb"></div>
        <div class="lib-grid" id="scene-grid">
          <div class="empty">
            <div class="empty-icon">⋯</div>
            <h2>Loading scenes…</h2>
          </div>
        </div>
        </div><!-- /tab-scenes -->

        <div class="tab-content" id="tab-addons">
        <div class="feedback" id="pack-fb"></div>
        <div class="addons-crumb" id="addons-crumb"></div>
        <div class="lib-grid" id="pack-grid">
          <div class="empty">
            <div class="empty-icon">⋯</div>
            <h2>Loading scene packs…</h2>
          </div>
        </div>
        </div><!-- /tab-addons -->

        <!-- Modals live outside the tab-content divs -- they're position:fixed
             overlays, so a tab switch (which sets display:none on an ancestor)
             must never be able to hide one while it's open. -->
        <div class="modal-overlay" id="upload-modal-overlay">
          <div class="modal-box">
            <h3>Upload to Library</h3>
            <div class="modal-row">
              <label>Photos</label>
              <!-- accept is deliberately just "image/*": the HA companion
                   apps' WebView file choosers are unreliable with
                   comma-separated multi-MIME accept lists (files select but
                   never attach), and image/* covers every type anyway. -->
              <input type="file" id="upload-modal-files" multiple accept="image/*">
              <div class="modal-file-summary" id="upload-modal-file-summary">No files selected</div>
            </div>
            <div class="modal-row">
              <label>Album</label>
              <select id="upload-modal-album"></select>
            </div>
            <div class="modal-row" id="upload-modal-new-album-row" style="display:none">
              <label>New album name</label>
              <input type="text" id="upload-modal-new-album" placeholder="e.g. Vacation 2026">
            </div>
            <div class="feedback" id="upload-modal-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="upload-modal-submit">⬆ Upload</button>
              <button class="btn-ghost" id="upload-modal-cancel">Cancel</button>
            </div>
            <!-- Deploy-verification breadcrumb: mobile WebViews have no
                 devtools console, so surface the running JS version where a
                 phone user can actually see it. -->
            <div class="modal-file-summary">panel v${PANEL_VERSION}</div>
          </div>
        </div>

        <div class="modal-overlay" id="album-picker-overlay">
          <div class="modal-box">
            <h3>Add to Album</h3>
            <div class="album-checklist" id="album-picker-list"></div>
            <div class="modal-row">
              <label>New album name</label>
              <input type="text" id="album-picker-new-name" placeholder="e.g. Vacation 2026">
            </div>
            <div class="feedback" id="album-picker-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="album-picker-save">Save</button>
              <button class="btn-ghost" id="album-picker-cancel">Cancel</button>
            </div>
          </div>
        </div>

        <div class="modal-overlay" id="album-create-overlay">
          <div class="modal-box" style="max-width:520px">
            <h3>Create Album</h3>
            <div class="modal-row">
              <label>Album name</label>
              <input type="text" id="album-create-name" placeholder="e.g. Vacation 2026">
            </div>
            <div class="modal-row">
              <label>Select photos</label>
              <div class="image-picker-grid" id="album-create-images"></div>
            </div>
            <div class="feedback" id="album-create-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="album-create-save">Create Album</button>
              <button class="btn-ghost" id="album-create-cancel">Cancel</button>
            </div>
          </div>
        </div>

        <!-- Hidden packer A/B test: only ever opened via /fraimic?packtest
             (see _init). Sends one image to two frames, one per packing
             method, bypassing the .bin cache -- for verifying the fast
             packer renders identically on real hardware. -->
        <div class="modal-overlay" id="packtest-overlay">
          <div class="modal-box" style="max-width:520px">
            <h3>🧪 Packer A/B Test</h3>
            <p class="muted" style="margin:0 0 12px">
              Sends one image to two frames — Frame A with the <strong>legacy</strong>
              packer, Frame B with the <strong>fast</strong> packer — bypassing the
              .bin cache so both really convert. The two panels should come out
              pixel-identical, including the dither pattern.
            </p>
            <div class="modal-row">
              <label for="packtest-album">Album</label>
              <select id="packtest-album"></select>
            </div>
            <div class="modal-row">
              <label>Pick one image</label>
              <div class="image-picker-grid" id="packtest-images"></div>
            </div>
            <div class="modal-row">
              <label for="packtest-frame-a">Frame A — legacy packer</label>
              <select id="packtest-frame-a"></select>
            </div>
            <div class="modal-row">
              <label for="packtest-frame-b">Frame B — fast packer</label>
              <select id="packtest-frame-b"></select>
            </div>
            <div class="modal-file-summary" id="packtest-log" style="white-space:pre-line"></div>
            <div class="feedback" id="packtest-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="packtest-go">▶ Go</button>
              <button class="btn-ghost" id="packtest-close">Close</button>
            </div>
          </div>
        </div>

        <!-- Not a centered modal-overlay like the others on purpose: this
             picker opens while positioning images on the wall canvas behind
             it, so it's a draggable floating panel (see _wireWallImagePicker)
             with no darkening backdrop, letting the wall stay visible and
             clickable around it. -->
        <div class="wall-picker-overlay" id="wall-image-picker-overlay">
          <div class="wall-picker-box" id="wall-image-picker-box">
            <div class="wall-picker-header" id="wall-image-picker-header">
              <h3>Choose an Image</h3>
              <button class="btn-ghost" id="wall-image-picker-cancel" style="flex:0 0 auto;padding:4px 10px">✕</button>
            </div>
            <div class="wall-picker-body">
              <div class="modal-row">
                <label for="wall-image-picker-album">Album</label>
                <select id="wall-image-picker-album"></select>
              </div>
              <div class="wall-lock-hint" id="wall-image-picker-lock-hint" style="display:none"></div>
              <div class="modal-row">
                <button class="btn-ghost" id="wall-image-picker-clear">✕ Remove Image From This Frame</button>
              </div>
              <div class="image-picker-grid" id="wall-image-picker-grid"></div>
              <div class="feedback" id="wall-image-picker-fb"></div>
            </div>
          </div>
        </div>

        <div class="modal-overlay" id="scene-editor-overlay">
          <div class="modal-box" style="max-width:480px">
            <h3 id="scene-editor-title">New Scene</h3>
            <div class="modal-row">
              <label>Scene name</label>
              <input type="text" id="scene-editor-name" placeholder="e.g. Countdown Wall">
            </div>
            <div class="modal-row">
              <label>Album</label>
              <select id="scene-editor-album"></select>
            </div>
            <div class="modal-row">
              <label>Image → Frame</label>
              <div id="scene-editor-mappings"></div>
            </div>
            <div class="feedback" id="scene-editor-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="scene-editor-save">Save Scene</button>
              <button class="btn-ghost" id="scene-editor-cancel">Cancel</button>
            </div>
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
            <div class="editor-row" id="editor-frame-row">
              <span class="editor-label">Target</span>
              <select id="editor-frame-select"></select>
            </div>
            <div class="editor-row">
              <span class="editor-hint" id="editor-frame-hint"></span>
            </div>
            <div class="editor-actions">
              <button class="btn-primary" id="editor-save-crop">💾 Save Crop</button>
              <button class="btn-primary" id="editor-send">⬆ Send to Canvas</button>
              <button class="btn-ghost" id="editor-add-album">＋ Add to Album</button>
              <button class="btn-ghost" id="editor-reset">↺ Reset crop</button>
              <button class="btn-ghost editor-danger" id="editor-delete">🗑 Delete</button>
              <button class="btn-ghost" id="editor-cancel">Cancel</button>
            </div>
            <div class="feedback" id="editor-fb"></div>
          </div>
        </div>

        <div class="editor-overlay" id="pack-preview-overlay">
          <div class="editor-header">
            <button class="editor-back" id="pack-preview-close" title="Close">←</button>
            <div class="editor-title" id="pack-preview-title"></div>
            <div class="pack-preview-counter" id="pack-preview-counter"></div>
          </div>
          <div class="editor-stage" id="pack-preview-stage">
            <button class="pack-preview-nav pack-preview-prev" id="pack-preview-prev" title="Previous image">‹</button>
            <img id="pack-preview-img" alt="">
            <button class="pack-preview-nav pack-preview-next" id="pack-preview-next" title="Next image">›</button>
          </div>
          <div class="pack-preview-caption" id="pack-preview-caption"></div>
        </div>

        <div class="modal-overlay" id="widget-config-overlay">
          <div class="modal-box" style="max-width:520px">
            <h3 id="widget-config-title">Configure Add-on</h3>
            <div id="widget-config-fields"></div>
            <div class="feedback" id="widget-config-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="widget-config-submit">Install</button>
              <button class="btn-ghost" id="widget-config-cancel">Cancel</button>
            </div>
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
          const orientationEntity = entities.find(e =>
            device && e.device_id === device.id &&
            (e.unique_id || '').endsWith('_orientation')
          );
          return {
            title:    entry.title,
            entityId: batteryEntity ? batteryEntity.entity_id : null,
            orientationEntityId: orientationEntity ? orientationEntity.entity_id : null,
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
            if (match) {
              frame.width    = match.width;
              frame.height   = match.height;
              frame.size     = match.size;
              frame.host     = match.host;
              frame.origin   = match.origin;
              frame.platform = match.platform;
              frame.orientation  = match.orientation;
              frame.lastImageId  = match.last_image_id;
              frame.hasThumbnail = match.has_thumbnail;
            }
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
            <div class="empty-icon">▦</div>
            <h2>No frames found</h2>
            <p>Go to <strong>Settings → Integrations → + Add Integration</strong>
               and search for <strong>Fraimic</strong> to set up your frames.</p>
          </div>
        `;
        return;
      }

      // frame.origin comes from /api/fraimic/frames (see FRAME_TYPES in
      // frame_types.py) and is only known once that fetch resolves; a frame
      // with no origin yet is grouped with Official rather than dropped, so
      // it doesn't flicker between sections as data arrives.
      const officialFrames = this._frames.filter(f => f.origin !== 'clone');
      const cloneFrames    = this._frames.filter(f => f.origin === 'clone');

      grid.innerHTML = '';
      this._cards = {};

      grid.appendChild(this._buildSectionHeader('🖼 Official Frames'));
      if (officialFrames.length) {
        for (const frame of officialFrames) {
          const card = this._buildCard(frame);
          grid.appendChild(card.el);
          this._cards[frame.entityId] = card;
        }
      } else {
        grid.appendChild(this._buildSectionEmpty('🖼', 'No official frames yet', 'Add a Fraimic Canvas frame to see it here.'));
      }

      if (cloneFrames.length) {
        grid.appendChild(this._buildSectionHeader('🧩 Community Frames'));
        for (const frame of cloneFrames) {
          const card = this._buildCard(frame);
          grid.appendChild(card.el);
          this._cards[frame.entityId] = card;
        }
      }

      // Wire reload buttons
      grid.querySelectorAll('.btn-reload').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const entryId = btn.dataset.entryId;
          btn.classList.add('loading');
          btn.disabled = true;
          try {
            const resp = await fetch('/api/fraimic/frame/reload', {
              method: 'POST',
              headers: {
                ...this._authHeaders(),
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({ entry_id: entryId })
            });
            if (resp.ok) {
              // Reloaded! Give HA a brief moment to re-initialize before
              // refreshing the view. (This used to call this._loadFrames(),
              // which doesn't exist -- the refresh silently never happened.)
              setTimeout(async () => {
                await this._discoverFrames();
                this._renderFrames();
              }, 2000);
            } else {
              alert('Failed to reload frame integration.');
            }
          } catch (err) {
            console.error('Error reloading frame:', err);
          } finally {
            btn.classList.remove('loading');
            btn.disabled = false;
          }
        });
      });

      // Wire the Options button: no documented URL opens the options dialog
      // for one specific entry directly, so this lands on the integration's
      // page (same place "Add entry" lives) where the kebab menu on this
      // frame's row opens Options -- reliable, uses the same navigate()
      // path as the Add Frame button above.
      grid.querySelectorAll('.btn-options').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          this._navigate('/config/integrations/integration/fraimic');
        });
      });

      // Wire orientation selects
      grid.querySelectorAll('.frame-orientation-select').forEach(select => {
        select.addEventListener('click', (e) => e.stopPropagation());
        select.addEventListener('change', async (e) => {
          const entityId = select.dataset.entityId;
          const option = e.target.value;
          select.disabled = true;
          try {
            await this._hass.callService('select', 'select_option', {
              entity_id: entityId,
              option,
            });
          } catch (err) {
            console.error('[fraimic-panel] failed to set orientation:', err);
            alert('Failed to change orientation.');
          } finally {
            select.disabled = false;
          }
        });
      });

      this._tickAllStatus();
    }

    _buildCard(frame) {
      const el = document.createElement('div');
      el.className = 'card frame-tile';
      const sid = this._sid(frame.entityId);
      const sizeLabel = frame.size ? `${this._esc(frame.size)}"` : '';
      const originLabel = frame.origin === 'clone'
        ? `Community Clone${frame.platform ? ` · ${this._esc(frame.platform)}` : ''}`
        : '';
      const hostLink = frame.host
        ? `<a class="frame-host-link" href="http://${this._esc(frame.host)}" target="_blank" rel="noopener" title="Open frame's web UI">
             <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
               <path d="M14 3h7v7"/><path d="M10 14 21 3"/>
               <path d="M21 14v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h6"/>
             </svg>
           </a>`
        : '';
      const reloadBtn = frame.entryId
        ? `<button class="frame-action-btn btn-reload" data-entry-id="${this._esc(frame.entryId)}" title="Reload Frame Integration">
             <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
               <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
             </svg>
           </button>`
        : '';
      const optionsBtn = frame.entryId
        ? `<button class="frame-action-btn btn-options" data-entry-id="${this._esc(frame.entryId)}" title="Frame Options">
             <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
               <circle cx="12" cy="12" r="3"/>
               <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
             </svg>
           </button>`
        : '';

      // Orientation select: options/labels are read live off the entity's own
      // state rather than hardcoded, so this stays correct if the labels in
      // select.py ever change -- see FraimicOrientationSelect.
      let orientationSelect = '';
      if (frame.orientationEntityId) {
        const state = this._hass.states[frame.orientationEntityId];
        const opts = (state && state.attributes && state.attributes.options) || [];
        if (opts.length) {
          orientationSelect = `
            <select class="frame-orientation-select" data-entity-id="${this._esc(frame.orientationEntityId)}" title="Orientation lock">
              ${opts.map(o => `<option value="${this._esc(o)}" ${state.state === o ? 'selected' : ''}>${this._esc(o)}</option>`).join('')}
            </select>`;
        }
      }

      // lastImageId (Library/Scene sends) and hasThumbnail (send_image
      // service / raw upload sends) are mutually exclusive on the backend --
      // see FraimicCoordinator.last_image_id / last_thumbnail -- so at most
      // one of these branches applies.
      let thumbSrc = null;
      if (frame.lastImageId) {
        thumbSrc = `/api/fraimic/library/image/${this._esc(frame.lastImageId)}?thumb=480`;
      } else if (frame.hasThumbnail) {
        thumbSrc = `/api/fraimic/frame/${this._esc(frame.entryId)}/thumbnail`;
      }
      const thumbIcon = thumbSrc
        ? `<img src="${thumbSrc}" alt="">`
        : `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
             <rect x="3" y="3" width="18" height="18" rx="2"/>
             <rect x="7" y="7" width="10" height="10" rx="1"/>
           </svg>`;

      el.innerHTML = `
        <div class="frame-row">
          <div class="frame-icon">${thumbIcon}</div>
          <div class="frame-meta">
            <div class="frame-name">${this._esc(frame.title)}</div>
            <div class="frame-status" id="status-${sid}"></div>
            ${sizeLabel ? `<div class="frame-status">${sizeLabel}</div>` : ''}
            ${originLabel ? `<div class="frame-origin-clone">${originLabel}</div>` : ''}
            ${orientationSelect}
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;align-items:center;flex-shrink:0">
            ${hostLink}
            ${reloadBtn}
            ${optionsBtn}
          </div>
        </div>
      `;

      return { el };
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
      let html;
      if (!state || state.state === 'unavailable' || state.state === 'unknown') {
        html = '<span class="dot-off">● Offline</span>';
      } else {
        const pct = parseFloat(state.state);
        const bat = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'} ${pct}%&nbsp; `;
        html = `${bat}<span class="dot-on">● Online</span>`;
      }
      // hass is re-assigned on every state change of ANY entity in the
      // house -- skip the DOM write when this frame's status text is
      // unchanged, or the constant innerHTML churn janks whatever screen
      // is open.
      if (statusEl._fraimicLastStatus === html) return;
      statusEl._fraimicLastStatus = html;
      statusEl.innerHTML = html;
    }

    // -----------------------------------------------------------------------
    // Library: toolbar wiring
    // -----------------------------------------------------------------------

    _wireLibraryToolbar() {
      const uploadBtn       = this.shadowRoot.getElementById('lib-upload-btn');
      const backendSelect   = this.shadowRoot.getElementById('backend-select');
      const backBtn         = this.shadowRoot.getElementById('lib-back-btn');
      const albumCreateBtn  = this.shadowRoot.getElementById('album-create-btn');
      const discoverBtn     = this.shadowRoot.getElementById('lib-discover-btn');
      const selectToggleBtn = this.shadowRoot.getElementById('lib-select-toggle');
      const selectCancelBtn = this.shadowRoot.getElementById('lib-select-cancel');
      const selectDeleteBtn = this.shadowRoot.getElementById('lib-select-delete');

      uploadBtn.addEventListener('click', () => this._openUploadModal());
      backendSelect.addEventListener('change', e => this._renderBackendConfig(e.target.value));
      backBtn.addEventListener('click', () => this._openAlbumFolders());
      albumCreateBtn.addEventListener('click', () => this._openAlbumCreateModal());
      discoverBtn.addEventListener('click', () => this._discoverLibrary());
      selectToggleBtn.addEventListener('click', () => this._setLibrarySelectMode(true));
      selectCancelBtn.addEventListener('click', () => this._setLibrarySelectMode(false));
      selectDeleteBtn.addEventListener('click', () => this._deleteSelectedFromLibrary());
    }

    // -----------------------------------------------------------------------
    // Library: multi-select delete
    // -----------------------------------------------------------------------

    _setLibrarySelectMode(on) {
      this._librarySelectMode = on;
      this._librarySelected = new Set();
      this._syncLibrarySelectUI();
      this._renderLibraryGrid();
    }

    _syncLibrarySelectUI() {
      const toolbar = this.shadowRoot.getElementById('lib-select-toolbar');
      const toggle  = this.shadowRoot.getElementById('lib-select-toggle');
      const count   = this.shadowRoot.getElementById('lib-select-count');
      const inAlbum = this._currentAlbum !== null;
      if (toolbar) toolbar.style.display = (inAlbum && this._librarySelectMode) ? 'flex' : 'none';
      if (toggle)  toggle.style.display  = (inAlbum && !this._librarySelectMode) ? '' : 'none';
      if (count)   count.textContent = `${this._librarySelected.size} selected`;
    }

    _toggleLibrarySelection(imageId, el) {
      if (this._librarySelected.has(imageId)) {
        this._librarySelected.delete(imageId);
        el.classList.remove('selected');
      } else {
        this._librarySelected.add(imageId);
        el.classList.add('selected');
      }
      this._syncLibrarySelectUI();
    }

    async _deleteSelectedFromLibrary() {
      const ids = [...this._librarySelected];
      if (!ids.length) return;
      if (!window.confirm(
        `Remove ${ids.length} photo${ids.length === 1 ? '' : 's'} from the library? This can't be undone.`
      )) return;

      const fb  = this.shadowRoot.getElementById('lib-fb');
      const btn = this.shadowRoot.getElementById('lib-select-delete');
      btn.disabled = true;

      // A small worker pool instead of one request per photo in sequence --
      // distinct-image deletes commute, and the backend serializes its own
      // manifest updates, so overlapping the HTTP round trips is safe.
      const failures = [];
      const queue = [...ids];
      const worker = async () => {
        for (let id = queue.shift(); id !== undefined; id = queue.shift()) {
          try {
            const resp = await fetch(`/api/fraimic/library/image/${id}`, {
              method: 'DELETE', headers: this._authHeaders(),
            });
            const result = await resp.json().catch(() => ({}));
            if (!resp.ok || !result.success) failures.push(id);
            else this._evictThumb(id);
          } catch (err) {
            failures.push(id);
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(4, ids.length) }, worker));
      btn.disabled = false;

      await this._loadAlbums();
      if (this._currentAlbum) await this._loadLibrary(this._currentAlbum);
      this._librarySelectMode = false;
      this._librarySelected = new Set();
      this._renderLibrary();

      if (failures.length) {
        fb.className = 'feedback err';
        fb.textContent = `Deleted ${ids.length - failures.length} of ${ids.length} photos -- ${failures.length} failed.`;
        fb.style.display = 'block';
      }
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
      this._syncDiscoverButton();
    }

    // Only Dropbox can see files a user drops into its storage outside the
    // app -- Google Drive's drive.file OAuth scope deliberately can't see
    // anything it didn't create itself, and Local storage lives inside HA's
    // own config dir, not somewhere a user casually drops photos into.
    _syncDiscoverButton() {
      const btn = this.shadowRoot.getElementById('lib-discover-btn');
      if (btn) btn.style.display = this._backend === 'dropbox' ? '' : 'none';
    }

    async _discoverLibrary() {
      const fb  = this.shadowRoot.getElementById('lib-fb');
      const btn = this.shadowRoot.getElementById('lib-discover-btn');
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Discovering…';

      try {
        const resp = await fetch('/api/fraimic/library/discover', {
          method: 'POST', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        await this._loadAlbums();
        if (this._currentAlbum) await this._loadLibrary(this._currentAlbum);
        this._renderLibrary();

        fb.className = 'feedback ok';
        fb.textContent = result.discovered
          ? `✓ Found ${result.discovered} new photo${result.discovered === 1 ? '' : 's'} -- generating previews in the background.`
          : '✓ Nothing new in the inbox folder.';
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Discover failed: ${err.message}`;
      }
      fb.style.display = 'block';
      btn.disabled = false;
      btn.textContent = prevText;
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
          this._syncDiscoverButton();
          this._currentAlbum = null;
          await this._loadAlbums();
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

    async _loadLibrary(album) {
      try {
        const url = album
          ? `/api/fraimic/library/list?album=${encodeURIComponent(album)}`
          : '/api/fraimic/library/list';
        const resp = await fetch(url, { headers: this._authHeaders() });
        const result = await resp.json();
        this._library = result.images || [];
        if (result.backend) this._backend = result.backend;
      } catch (err) {
        console.error('[fraimic-panel] library load failed:', err);
        this._library = [];
      }
    }

    async _loadAlbums() {
      try {
        const resp = await fetch('/api/fraimic/library/albums', { headers: this._authHeaders() });
        const result = await resp.json();
        this._albums = result.albums || [];
      } catch (err) {
        console.error('[fraimic-panel] albums load failed:', err);
        this._albums = [];
      }
    }

    _openAlbumFolders() {
      this._currentAlbum = null;
      this._renderLibrary();
    }

    async _openAlbum(name) {
      this._currentAlbum = name;
      await this._loadLibrary(name);
      this._renderLibrary();
    }

    _renderLibrary() {
      const breadcrumb     = this.shadowRoot.getElementById('lib-breadcrumb');
      const title          = this.shadowRoot.getElementById('lib-breadcrumb-title');
      const albumCreateBtn = this.shadowRoot.getElementById('album-create-btn');

      if (this._currentAlbum === null) {
        breadcrumb.style.display = 'none';
        albumCreateBtn.style.display = '';
        this._librarySelectMode = false;
        this._librarySelected = new Set();
        this._syncLibrarySelectUI();
        this._renderAlbumFolders();
        return;
      }

      breadcrumb.style.display = 'flex';
      albumCreateBtn.style.display = 'none';
      title.textContent = `📁 ${this._currentAlbum}`;
      this._syncLibrarySelectUI();
      this._renderLibraryGrid();
    }

    _renderAlbumFolders() {
      const grid = this.shadowRoot.getElementById('lib-grid');

      // The default album is always present (even with 0 photos), so
      // "library is empty" has to be judged by total photo count, not
      // album count.
      const totalPhotos = this._albums.reduce((sum, a) => sum + a.count, 0);
      if (!totalPhotos) {
        grid.innerHTML = `
          <div class="empty">
            <div class="empty-icon">▤</div>
            <h2>Library is empty</h2>
            <p>Upload photos above to add them to the shared library. They're converted
               once per frame resolution and reused by every frame that matches —
               no need to re-upload per frame.</p>
          </div>
        `;
        return;
      }

      // An album created by a scene pack install shares its name with the
      // pack (see ScenePackManager.async_install_pack: album = pack["name"]).
      // Matching on that, rather than tracking a separate flag, means this
      // stays correct even for packs installed before this grouping existed.
      const addonAlbumNames = new Set(
        (this._scenePacks || []).filter(p => p.installed).map(p => p.name)
      );
      const userAlbums  = this._albums.filter(a => !addonAlbumNames.has(a.name));
      const addonAlbums = this._albums.filter(a => addonAlbumNames.has(a.name));

      grid.innerHTML = '';

      grid.appendChild(this._buildSectionHeader('👤 Your Albums'));
      if (userAlbums.length) {
        for (const album of userAlbums) grid.appendChild(this._buildAlbumTile(album));
      } else {
        grid.appendChild(this._buildSectionEmpty('📁', 'No albums yet', 'Upload a photo to create one.'));
      }

      if (addonAlbums.length) {
        grid.appendChild(this._buildSectionHeader('🧩 Add-on Albums'));
        for (const album of addonAlbums) grid.appendChild(this._buildAlbumTile(album));
      }
    }

    _buildAlbumTile(album) {
      const el = document.createElement('div');
      el.className = 'card album-tile';
      const sid = this._sid(album.name);
      const isDefault = album.name === DEFAULT_ALBUM;

      el.innerHTML = `
        <div class="lib-thumb" id="album-thumb-${sid}">
          <div style="font-size:32px;text-align:center;padding:30px 0">📁</div>
        </div>
        <div class="album-name">${this._esc(album.name)}</div>
        <div class="album-count">${album.count} photo${album.count === 1 ? '' : 's'}</div>
        ${isDefault ? '' : `
          <div class="album-tile-actions">
            <button class="btn-ghost" id="album-rename-${sid}">✎ Rename</button>
            <button class="btn-ghost" id="album-delete-${sid}">🗑 Delete</button>
          </div>
        `}
      `;

      if (album.cover_image_id) {
        this._loadThumbnail(album.cover_image_id, el.querySelector(`#album-thumb-${sid}`));
      }

      const open = () => this._openAlbum(album.name);
      el.querySelector(`#album-thumb-${sid}`).addEventListener('click', open);
      el.querySelector('.album-name').addEventListener('click', open);

      const renameBtn = el.querySelector(`#album-rename-${sid}`);
      if (renameBtn) renameBtn.addEventListener('click', e => { e.stopPropagation(); this._renameAlbum(album.name); });
      const deleteBtn = el.querySelector(`#album-delete-${sid}`);
      if (deleteBtn) deleteBtn.addEventListener('click', e => { e.stopPropagation(); this._deleteAlbum(album.name); });

      return el;
    }

    async _renameAlbum(oldName) {
      const newName = window.prompt(`Rename album "${oldName}" to:`, oldName);
      if (!newName || !newName.trim() || newName.trim() === oldName) return;

      const fb = this.shadowRoot.getElementById('lib-fb');
      try {
        const resp = await fetch('/api/fraimic/library/albums', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_name: oldName, new_name: newName.trim() }),
        });
        const result = await resp.json().catch(() => ({}));
        if (resp.ok && result.success) {
          await this._loadAlbums();
          this._renderLibrary();
          return;
        }
        fb.className = 'feedback err';
        fb.textContent = `Rename failed: ${result.message || resp.statusText || resp.status}`;
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
    }

    async _deleteAlbum(name) {
      if (!window.confirm(
        `Delete album "${name}"? Photos in it aren't deleted — they'll just no longer be tagged with this album.`
      )) return;

      const fb = this.shadowRoot.getElementById('lib-fb');
      try {
        const resp = await fetch('/api/fraimic/library/albums', {
          method: 'DELETE',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        const result = await resp.json().catch(() => ({}));
        if (resp.ok && result.success) {
          await this._loadAlbums();
          this._renderLibrary();
          return;
        }
        fb.className = 'feedback err';
        fb.textContent = `Delete failed: ${result.message || resp.statusText || resp.status}`;
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
    }

    _renderLibraryGrid() {
      const grid = this.shadowRoot.getElementById('lib-grid');

      if (!this._library.length) {
        grid.innerHTML = `
          <div class="empty">
            <div class="empty-icon">▤</div>
            <h2>No photos in "${this._esc(this._currentAlbum)}" yet</h2>
            <p>Upload photos into this album, or use "＋ Add to Album" on an existing photo.</p>
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
      const sid = this._sid(image.image_id);

      if (this._librarySelectMode) {
        el.className = 'card lib-card selectable';
        el.classList.toggle('selected', this._librarySelected.has(image.image_id));
        el.innerHTML = `
          <div class="lib-thumb" id="thumb-${sid}">
            <div style="font-size:32px;text-align:center;padding:30px 0">🖼</div>
            <div class="lib-select-check">✓</div>
          </div>
          <div class="preview-name">${this._esc(image.filename)}</div>
        `;
        this._loadThumbnail(image.image_id, el.querySelector(`#thumb-${sid}`));
        el.addEventListener('click', () => this._toggleLibrarySelection(image.image_id, el));
        return el;
      }

      el.className = 'card lib-card';
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
            ${this._frames.length ? '<option value="">Select a Frame</option>' : ''}
            ${frameOptions || '<option>No frames available</option>'}
          </select>
          <button class="btn-primary" id="lib-send-${sid}" ${this._frames.length ? '' : 'disabled'}>⬆ Send</button>
        </div>
        <div class="btns">
          <button class="btn-ghost" id="lib-album-${sid}" title="Add to album">🏷 Album</button>
          <button class="btn-ghost" id="lib-delete-${sid}" title="Remove from library">🗑 Delete</button>
        </div>
        <div class="feedback" id="lib-card-fb-${sid}"></div>
      `;

      this._loadThumbnail(image.image_id, el.querySelector(`#thumb-${sid}`));

      el.querySelector(`#thumb-${sid}`).addEventListener('click', () => {
        this._openEditor(image);
      });

      el.querySelector(`#lib-send-${sid}`).addEventListener('click', () => {
        const entityId = el.querySelector(`#frame-select-${sid}`).value;
        if (!entityId) {
          const fb = el.querySelector(`#lib-card-fb-${sid}`);
          fb.className = 'feedback err';
          fb.textContent = 'Choose a frame first.';
          fb.style.display = 'block';
          return;
        }
        this._sendFromLibrary(image.image_id, entityId, el, sid);
      });

      el.querySelector(`#lib-album-${sid}`).addEventListener('click', () => {
        this._openAlbumPicker(image);
      });

      el.querySelector(`#lib-delete-${sid}`).addEventListener('click', () => {
        this._deleteFromLibrary(image.image_id);
      });

      return el;
    }

    // Paints the small server-side thumbnail (?thumb=) into `container`.
    // Cached hits paint synchronously -- callers (and the wall regression
    // test) rely on an unchanged tile keeping its blob URL across renders.
    // Uncached tiles are handed to the IntersectionObserver and only fetch
    // once they come near the viewport, via the concurrency-capped queue.
    _loadThumbnail(imageId, container) {
      const cached = this._thumbUrls[imageId];
      if (cached) {
        container.innerHTML = `<img src="${cached}" alt="">`;
        return;
      }
      container._fraimicThumbId = imageId;
      if (this._thumbObserver) {
        this._thumbObserver.observe(container);
      } else {
        // No IntersectionObserver (ancient WebView) -- load eagerly.
        this._enqueueThumbFetch(imageId, container);
      }
    }

    _enqueueThumbFetch(imageId, container) {
      this._thumbQueue.push({ imageId, container });
      this._pumpThumbQueue();
    }

    _pumpThumbQueue() {
      const MAX_CONCURRENT = 6;
      while (this._thumbActive < MAX_CONCURRENT && this._thumbQueue.length) {
        const { imageId, container } = this._thumbQueue.shift();
        this._thumbActive++;
        this._fetchThumb(imageId, container);
      }
    }

    async _fetchThumb(imageId, container) {
      try {
        // May have landed while this tile sat in the queue (same image on
        // another tile, or the grid re-rendered a cached image).
        const cached = this._thumbUrls[imageId];
        if (cached) {
          container.innerHTML = `<img src="${cached}" alt="">`;
          return;
        }
        if (!this._thumbFetches[imageId]) {
          this._thumbFetches[imageId] = (async () => {
            const resp = await fetch(`/api/fraimic/library/image/${imageId}?thumb=480`, { headers: this._authHeaders() });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const blob = await resp.blob();
            const url  = URL.createObjectURL(blob);
            this._thumbUrls[imageId] = url;
            return url;
          })();
        }
        const url = await this._thumbFetches[imageId];
        container.innerHTML = `<img src="${url}" alt="">`;
      } catch (err) {
        delete this._thumbFetches[imageId]; // allow a later retry
        console.warn('[fraimic-panel] thumbnail load failed:', err);
      } finally {
        this._thumbActive--;
        this._pumpThumbQueue();
      }
    }

    // Drop a deleted image's thumbnail so the blob memory is released --
    // the shared cache is otherwise kept for the panel's lifetime.
    _evictThumb(imageId) {
      const url = this._thumbUrls[imageId];
      if (url) URL.revokeObjectURL(url);
      delete this._thumbUrls[imageId];
      delete this._thumbFetches[imageId];
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
          this._evictThumb(imageId);
          await this._loadAlbums();
          if (this._currentAlbum) await this._loadLibrary(this._currentAlbum);
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

    _wireUploadModal() {
      const filesInput  = this.shadowRoot.getElementById('upload-modal-files');
      const albumSelect = this.shadowRoot.getElementById('upload-modal-album');
      const newAlbumRow = this.shadowRoot.getElementById('upload-modal-new-album-row');

      // Root cause of "files select but never attach" in the HA Android
      // companion app: Android WebView's stock file-chooser result parsing
      // (FileChooserParams.parseResult) returns null for picker results
      // delivered via clipData -- and multi-select pickers reply via
      // clipData even when the user picks a SINGLE photo. With `multiple`
      // set, the page therefore never receives any files at all. Mobile
      // Chrome parses clipData fine (uploads work in a phone browser), so
      // only the companion app's WebView needs single-select mode. Picks
      // accumulate in _uploadPendingFiles instead, so multi-photo uploads
      // still work -- tap the picker once per photo.
      const ua = navigator.userAgent || '';
      this._singleFilePicks = ua.includes('Home Assistant') && ua.includes('Android');
      if (this._singleFilePicks) filesInput.removeAttribute('multiple');

      this._uploadPendingFiles = [];
      const captureFiles = () => {
        if (filesInput.files && filesInput.files.length) {
          for (const f of Array.from(filesInput.files)) {
            const dup = this._uploadPendingFiles.some(p =>
              p.name === f.name && p.size === f.size && p.lastModified === f.lastModified);
            if (!dup) this._uploadPendingFiles.push(f);
          }
          // Clear the native input so picking again (even the same photo)
          // fires a fresh change event -- the File objects captured above
          // stay alive in _uploadPendingFiles regardless.
          filesInput.value = '';
        }
        this._renderUploadFileSummary();
      };
      filesInput.addEventListener('change', captureFiles);
      filesInput.addEventListener('input', captureFiles);
      // Last-resort sweep for WebViews that fire neither event on return
      // from the picker: re-check the input whenever the page regains focus
      // or becomes visible again (Android fires visibilitychange, not
      // window focus, when returning from the picker activity). Kept as
      // instance fields and registered via _addGlobalListeners so the
      // element lifecycle can detach/re-attach them.
      this._sweepUploadInput = () => {
        const overlay = this.shadowRoot.getElementById('upload-modal-overlay');
        if (overlay && overlay.style.display !== 'none' && overlay.style.display !== '') captureFiles();
      };
      this._onDocVisibility = () => {
        if (!document.hidden) this._sweepUploadInput();
      };

      albumSelect.addEventListener('change', () => {
        newAlbumRow.style.display = albumSelect.value === '' ? 'block' : 'none';
      });

      this.shadowRoot.getElementById('upload-modal-cancel').addEventListener('click', () => this._closeUploadModal());
      this.shadowRoot.getElementById('upload-modal-submit').addEventListener('click', () => this._submitUpload());
    }

    _renderUploadFileSummary() {
      const el = this.shadowRoot.getElementById('upload-modal-file-summary');
      const n = (this._uploadPendingFiles || []).length;
      if (!n) {
        el.textContent = 'No files selected';
        return;
      }
      // Filenames are user data -- keep them out of innerHTML entirely.
      const hint = this._singleFilePicks ? ' · pick again to add more' : '';
      el.innerHTML = `<span></span>${hint} · <a href="#" id="upload-modal-clear-files">clear</a>`;
      el.querySelector('span').textContent = `${n} file${n === 1 ? '' : 's'} selected`;
      el.querySelector('#upload-modal-clear-files').addEventListener('click', (e) => {
        e.preventDefault();
        this._uploadPendingFiles = [];
        this.shadowRoot.getElementById('upload-modal-files').value = '';
        this._renderUploadFileSummary();
      });
    }

    _openUploadModal() {
      const overlay      = this.shadowRoot.getElementById('upload-modal-overlay');
      const filesInput    = this.shadowRoot.getElementById('upload-modal-files');
      const albumSelect   = this.shadowRoot.getElementById('upload-modal-album');
      const newAlbumRow   = this.shadowRoot.getElementById('upload-modal-new-album-row');
      const newAlbumInput = this.shadowRoot.getElementById('upload-modal-new-album');
      const fb            = this.shadowRoot.getElementById('upload-modal-fb');

      filesInput.value = '';
      this._uploadPendingFiles = [];
      this._renderUploadFileSummary();
      newAlbumInput.value = '';
      fb.style.display = 'none';

      // Real album names are never empty (server-side normalization strips
      // blanks), so '' is a safe sentinel that can't collide with a
      // user-created album literally named e.g. "__new__".
      albumSelect.innerHTML = this._albums.map(a =>
        `<option value="${this._esc(a.name)}">${this._esc(a.name)}</option>`
      ).join('') + `<option value="">＋ New album…</option>`;

      // Default to whichever album is currently open, otherwise the default album.
      const preferred = this._currentAlbum || DEFAULT_ALBUM;
      if ([...albumSelect.options].some(o => o.value === preferred)) {
        albumSelect.value = preferred;
      }
      newAlbumRow.style.display = albumSelect.value === '' ? 'block' : 'none';

      overlay.style.display = 'flex';
    }

    _closeUploadModal() {
      this.shadowRoot.getElementById('upload-modal-overlay').style.display = 'none';
      this._uploadPendingFiles = [];
    }

    async _submitUpload() {
      const filesInput    = this.shadowRoot.getElementById('upload-modal-files');
      const albumSelect   = this.shadowRoot.getElementById('upload-modal-album');
      const newAlbumInput = this.shadowRoot.getElementById('upload-modal-new-album');
      const fb            = this.shadowRoot.getElementById('upload-modal-fb');
      const submitBtn     = this.shadowRoot.getElementById('upload-modal-submit');

      // Prefer the selection captured at pick time (see _wireUploadModal --
      // some mobile WebViews clear input.files by the time Upload is hit),
      // falling back to whatever the input holds right now.
      let files = this._uploadPendingFiles && this._uploadPendingFiles.length
        ? this._uploadPendingFiles
        : (filesInput.files ? Array.from(filesInput.files) : []);
      if (!files.length) {
        fb.className = 'feedback err';
        fb.textContent = 'Choose at least one photo.';
        fb.style.display = 'block';
        return;
      }

      const isNew = albumSelect.value === '';
      const newAlbumName = newAlbumInput.value.trim();
      if (isNew && !newAlbumName) {
        fb.className = 'feedback err';
        fb.textContent = 'Enter a name for the new album.';
        fb.style.display = 'block';
        return;
      }

      const form = new FormData();
      for (const file of files) form.append('image', file);
      if (isNew) form.append('new_album', newAlbumName);
      else form.append('album', albumSelect.value);

      submitBtn.disabled = true;
      submitBtn.textContent = '⏳ Uploading…';
      fb.style.display = 'none';

      try {
        const resp = await fetch('/api/fraimic/library/upload', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));
        const uploaded = (result.images || []).length;
        const errors   = result.errors || [];

        // Refresh as soon as anything landed -- a later file failing
        // shouldn't hide the ones that already succeeded.
        if (uploaded) {
          await this._loadAlbums();
          if (this._currentAlbum) await this._loadLibrary(this._currentAlbum);
          this._renderLibrary();
        }

        if (resp.ok && result.success && !errors.length) {
          this._closeUploadModal();
        } else if (uploaded) {
          filesInput.value = '';
          this._uploadPendingFiles = [];
          this._renderUploadFileSummary();
          fb.className = 'feedback err';
          fb.textContent = `Uploaded ${uploaded} of ${uploaded + errors.length} — `
            + `failed: ${errors.map(e => e.filename).join(', ')}`;
          fb.style.display = 'block';
        } else {
          fb.className = 'feedback err';
          fb.textContent = `Upload failed: ${(errors[0] && errors[0].message) || result.message || resp.statusText || resp.status}`;
          fb.style.display = 'block';
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
        fb.style.display = 'block';
      }

      submitBtn.disabled = false;
      submitBtn.textContent = '⬆ Upload';
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
      if (this._packerOverride) form.append('packer', this._packerOverride);

      try {
        const resp = await fetch('/api/fraimic/library/send', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));

        if (resp.ok && result.success) {
          fb.className = 'feedback ok';
          fb.textContent = result.packer ? `✓ Sent! (packer: ${result.packer})` : '✓ Sent!';
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
    // Packer A/B test modal (hidden -- only reachable via /fraimic?packtest)
    // -----------------------------------------------------------------------

    _wirePackTest() {
      this.shadowRoot.getElementById('packtest-close').addEventListener('click', () => {
        this.shadowRoot.getElementById('packtest-overlay').style.display = 'none';
      });
      this.shadowRoot.getElementById('packtest-album').addEventListener('change', () => this._loadPackTestImages());
      this.shadowRoot.getElementById('packtest-go').addEventListener('click', () => this._runPackTest());
    }

    async _openPackTestModal() {
      const overlay     = this.shadowRoot.getElementById('packtest-overlay');
      const albumSelect = this.shadowRoot.getElementById('packtest-album');
      const selA        = this.shadowRoot.getElementById('packtest-frame-a');
      const selB        = this.shadowRoot.getElementById('packtest-frame-b');
      const fb          = this.shadowRoot.getElementById('packtest-fb');

      fb.style.display = 'none';
      this.shadowRoot.getElementById('packtest-log').textContent = '';

      const frameOptions = this._frames.map(f =>
        `<option value="${this._esc(f.entityId)}">${this._esc(f.title)}</option>`
      ).join('');
      selA.innerHTML = frameOptions;
      selB.innerHTML = frameOptions;
      // Default to two different frames -- ideally the same model side by
      // side, but any second frame beats defaulting both to the same one.
      if (this._frames.length > 1) selB.selectedIndex = 1;

      if (!this._albums || !this._albums.length) await this._loadAlbums();
      albumSelect.innerHTML = '<option value="">All Photos</option>' +
        this._albums.map(a => `<option value="${this._esc(a.name)}">${this._esc(a.name)}</option>`).join('');

      overlay.style.display = 'flex';
      await this._loadPackTestImages();
    }

    async _loadPackTestImages() {
      const grid  = this.shadowRoot.getElementById('packtest-images');
      const album = this.shadowRoot.getElementById('packtest-album').value;
      this._packTestSelectedImage = null;
      grid.innerHTML = '<div class="modal-file-summary">Loading photos…</div>';

      let images = [];
      try {
        const url = album
          ? `/api/fraimic/library/list?album=${encodeURIComponent(album)}`
          : '/api/fraimic/library/list';
        const resp = await fetch(url, { headers: this._authHeaders() });
        const result = await resp.json();
        images = result.images || [];
      } catch (err) {
        console.warn('[fraimic-panel] library load for packer test failed:', err);
      }

      if (!images.length) {
        grid.innerHTML = '<div class="modal-file-summary">No photos here yet.</div>';
        return;
      }

      grid.innerHTML = '';
      for (const image of images) {
        const cell = document.createElement('div');
        cell.className = 'image-picker-cell';
        cell.dataset.imageId = image.image_id;
        cell.title = image.filename;
        cell.innerHTML = `<div class="image-picker-thumb">🖼</div>`;
        this._loadThumbnail(image.image_id, cell.querySelector('.image-picker-thumb'));
        cell.addEventListener('click', () => {
          grid.querySelectorAll('.image-picker-cell.selected').forEach(c => c.classList.remove('selected'));
          cell.classList.add('selected');
          this._packTestSelectedImage = image.image_id;
        });
        grid.appendChild(cell);
      }
    }

    // Sends the picked image twice, one frame at a time: Frame A with the
    // legacy packer, Frame B with the fast packer. Each send carries the
    // packer override, which makes the backend bypass the .bin cache in
    // both directions (see LibraryManager.async_get_bin_for_send).
    async _runPackTest() {
      const fb  = this.shadowRoot.getElementById('packtest-fb');
      const log = this.shadowRoot.getElementById('packtest-log');
      const btn = this.shadowRoot.getElementById('packtest-go');
      const imageId  = this._packTestSelectedImage;
      const entityA  = this.shadowRoot.getElementById('packtest-frame-a').value;
      const entityB  = this.shadowRoot.getElementById('packtest-frame-b').value;

      const fail = (msg) => {
        fb.className = 'feedback err';
        fb.textContent = msg;
        fb.style.display = 'block';
      };
      fb.style.display = 'none';
      if (!imageId) return fail('Pick an image first.');
      if (!entityA || !entityB) return fail('Pick both frames.');
      if (entityA === entityB) return fail('Pick two different frames.');

      btn.disabled = true;
      log.textContent = '';
      let failed = false;

      for (const [entityId, packer] of [[entityA, 'legacy'], [entityB, 'fast']]) {
        const frame = this._frames.find(f => f.entityId === entityId);
        const name = frame ? frame.title : entityId;
        log.textContent += `Sending with ${packer} packer to "${name}" (cache bypassed)…\n`;
        const t0 = performance.now();
        try {
          // URL-encoded rather than FormData purely for simplicity -- the
          // backend's request.post() parses both identically.
          const resp = await fetch('/api/fraimic/library/send', {
            method: 'POST',
            headers: { ...this._authHeaders(), 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ entity_id: entityId, image_id: imageId, packer }),
          });
          const result = await resp.json().catch(() => ({}));
          if (!resp.ok || !result.success) {
            throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
          }
          const secs = ((performance.now() - t0) / 1000).toFixed(1);
          log.textContent += `  ✓ done in ${secs}s (${result.bytes_sent} bytes)\n`;
        } catch (err) {
          const secs = ((performance.now() - t0) / 1000).toFixed(1);
          log.textContent += `  ✗ failed after ${secs}s: ${err.message}\n`;
          failed = true;
          break;
        }
      }

      if (!failed) {
        log.textContent += '\nDone. Compare the two frames — they should be pixel-identical, dither pattern included.';
      }
      btn.disabled = false;
    }

    // -----------------------------------------------------------------------
    // Library: crop editor (aspect dictated by the selected frame)
    // -----------------------------------------------------------------------

    // Frames the crop editor can target: anything discovery found with
    // usable render dimensions. width/height here are the frame's
    // *effective* composition dimensions from /api/fraimic/frames -- they
    // already reflect the frame's orientation lock, so the crop box aspect
    // simply follows the selected frame. No free size/orientation choice:
    // the frame dictates the shape (that's the whole point of the lock).
    _editorFrames() {
      return this._frames.filter(f =>
        Number.isInteger(f.width) && Number.isInteger(f.height)
      );
    }

    // Human summary of where a crop is headed, shown under the frame select.
    _editorFrameLabel(frame) {
      const portrait = frame.height >= frame.width;
      const orient = portrait ? 'portrait' : 'landscape';
      const locked = frame.orientation && frame.orientation !== 'auto';
      const size = frame.size ? `${frame.size}" ` : '';
      return `${size}${orient}${locked ? ' (locked)' : ''}`;
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
      root.getElementById('editor-save-crop').addEventListener('click', () => this._editorSaveCropAction());
      root.getElementById('editor-send').addEventListener('click', () => this._editorSendToCanvas());
      root.getElementById('editor-delete').addEventListener('click', () => this._editorDeleteImage());

      // The frame select drives the crop aspect: picking a different frame
      // reloads that frame's saved crop (or a centered cover box).
      root.getElementById('editor-frame-select').addEventListener('change', (e) => {
        if (this._editorState) this._editorSetFrame(e.target.value);
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

    // Open the editor for a library image. Defaults to whichever frame
    // already has a saved crop for its effective resolution (if any), loads
    // the full image, then renders.
    async _openEditor(image) {
      const frames = this._editorFrames();

      // Default to whichever frame or orientation already has a saved crop.
      let initialVal = 'generic_portrait';
      if (image.crops && image.crops['portrait']) {
        initialVal = 'generic_portrait';
      } else if (image.crops && image.crops['landscape']) {
        initialVal = 'generic_landscape';
      }

      for (const frame of frames) {
        const key = `${frame.width}x${frame.height}`;
        if (image.crops && image.crops[key]) {
          initialVal = frame.entityId;
          break;
        }
      }

      this._editorState = {
        image,
        frameEntityId: initialVal,
        targetWidth: 0,
        targetHeight: 0,
        naturalW: 0,
        naturalH: 0,
        cropBox: null,
        cropIsSaved: false,
      };

      const select = this.shadowRoot.getElementById('editor-frame-select');
      this.shadowRoot.getElementById('editor-reset').disabled = false;
      this.shadowRoot.getElementById('editor-add-album').disabled = false;

      let optionsHtml = '';
      optionsHtml += `<optgroup label="Generic Orientations">`;
      optionsHtml += `<option value="generic_portrait">Generic Portrait (3:4)</option>`;
      optionsHtml += `<option value="generic_landscape">Generic Landscape (16:9)</option>`;
      optionsHtml += `</optgroup>`;
      if (frames.length > 0) {
        optionsHtml += `<optgroup label="Frames">`;
        optionsHtml += frames.map(f =>
          `<option value="${this._esc(f.entityId)}">${this._esc(f.title)} — ${this._esc(this._editorFrameLabel(f))}</option>`
        ).join('');
        optionsHtml += `</optgroup>`;
      }

      select.innerHTML = optionsHtml;
      select.disabled = false;
      select.value = initialVal;

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

      this._editorSetFrame(this._editorState.frameEntityId);
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

    _editorSetFrame(entityId) {
      const st = this._editorState;
      let targetWidth, targetHeight, key, isGeneric = false;

      if (entityId === 'generic_portrait') {
        targetWidth = 1200;
        targetHeight = 1600;
        key = 'portrait';
        isGeneric = true;
        st.frameEntityId = 'generic_portrait';
      } else if (entityId === 'generic_landscape') {
        targetWidth = 2560;
        targetHeight = 1440;
        key = 'landscape';
        isGeneric = true;
        st.frameEntityId = 'generic_landscape';
      } else {
        const frame = this._editorFrames().find(f => f.entityId === entityId)
          || this._editorFrames()[0];
        if (frame) {
          targetWidth = frame.width;
          targetHeight = frame.height;
          key = `${frame.width}x${frame.height}`;
          st.frameEntityId = frame.entityId;
        } else {
          // If no frames exist at all
          targetWidth = 1200;
          targetHeight = 1600;
          key = 'portrait';
          isGeneric = true;
          st.frameEntityId = 'generic_portrait';
        }
      }

      st.targetWidth = targetWidth;
      st.targetHeight = targetHeight;

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
        st.cropBox = this._editorComputeCoverBox(st.naturalW, st.naturalH, targetWidth, targetHeight, cx, cy);
        st.cropIsSaved = false;
      }

      const hint = this.shadowRoot.getElementById('editor-frame-hint');
      const sendBtn = this.shadowRoot.getElementById('editor-send');
      if (isGeneric) {
        sendBtn.disabled = true;
        sendBtn.title = 'Select a physical frame to enable sending.';
        if (st.frameEntityId === 'generic_portrait') {
          hint.textContent = 'Generic 3:4 portrait aspect ratio crop. Saved to "portrait" fallback.';
        } else {
          hint.textContent = 'Generic 16:9 landscape aspect ratio crop. Saved to "landscape" fallback.';
        }
      } else {
        sendBtn.disabled = false;
        sendBtn.title = '';
        const frame = this._editorFrames().find(f => f.entityId === st.frameEntityId);
        const portrait = frame.height >= frame.width;
        const locked = frame.orientation && frame.orientation !== 'auto';
        hint.textContent = locked
          ? `Frame is locked to ${frame.orientation} — adjust the ${portrait ? 'portrait' : 'landscape'} crop window below.`
          : `Crop follows this frame's current ${portrait ? 'portrait' : 'landscape'} orientation.`;
      }

      this._editorRenderCropBox();
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
      el.style.display = '';
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
      // signal: if the panel is detached mid-drag, _dispose severs these.
      window.addEventListener('pointermove', this._onEditorPointerMove, { signal: this._abort.signal });
      window.addEventListener('pointerup', this._onEditorPointerUp, { signal: this._abort.signal });
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

      // State updates stay synchronous (pointerup persists cropBox); only
      // the DOM render is coalesced to one write per frame.
      this._editorState.cropBox = box;
      if (this._editorRenderRaf) return;
      this._editorRenderCropBox();
      this._editorRenderRaf = requestAnimationFrame(() => {
        this._editorRenderRaf = null;
        if (this._editorState) this._editorRenderCropBox();
      });
    }

    _onEditorPointerUp() {
      this._editorDrag = null;
      window.removeEventListener('pointermove', this._onEditorPointerMove);
      window.removeEventListener('pointerup', this._onEditorPointerUp);
      if (this._editorRenderRaf) {
        cancelAnimationFrame(this._editorRenderRaf);
        this._editorRenderRaf = null;
      }
      if (this._editorState) {
        this._editorState.cropIsSaved = false;
        this._editorRenderCropBox(); // land exactly on the final box
      }
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
      let w = st.targetWidth;
      let h = st.targetHeight;
      if (st.frameEntityId === 'generic_portrait') {
        w = 'portrait';
        h = 0;
      } else if (st.frameEntityId === 'generic_landscape') {
        w = 'landscape';
        h = 0;
      }

      const resp = await fetch('/api/fraimic/library/crop', {
        method: 'POST',
        headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_id: st.image.image_id,
          width: w,
          height: h,
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

    async _editorSaveCropAction() {
      const btn = this.shadowRoot.getElementById('editor-save-crop');
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Saving…';
      try {
        await this._editorSaveCrop();
        this._editorShowFb('ok', '✓ Crop saved!');
      } catch (err) {
        this._editorShowFb('err', `Failed to save crop: ${err.message}`);
      }
      btn.disabled = false;
      btn.textContent = prevText;
    }

    // Reverts to the original (uncropped/letterboxed) framing for the
    // current size+orientation -- distinct from Cancel, which just discards
    // unsaved in-editor changes without touching what's persisted.
    async _editorResetCrop() {
      const st = this._editorState;
      let w = st.targetWidth;
      let h = st.targetHeight;
      if (st.frameEntityId === 'generic_portrait') {
        w = 'portrait';
        h = 0;
      } else if (st.frameEntityId === 'generic_landscape') {
        w = 'landscape';
        h = 0;
      }
      try {
        const resp = await fetch('/api/fraimic/library/crop', {
          method: 'DELETE',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_id: st.image.image_id, width: w, height: h }),
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
        this._editorShowFb('ok', 'Reverted to the automatic framing for this target.');
      } catch (err) {
        this._editorShowFb('err', `Couldn't reset crop: ${err.message}`);
      }
    }

    async _editorAddToAlbum() {
      try {
        // Preserve whatever crop adjustment the user was mid-editing.
        await this._editorSaveCrop();
      } catch (err) {
        // Surface the failure rather than silently discarding the edit --
        // still open the picker so album management isn't blocked by it.
        this._editorShowFb('err', `Couldn't save crop: ${err.message}`);
      }
      await this._openAlbumPicker(this._editorState.image);
    }

    // -----------------------------------------------------------------------
    // Album picker (used from the crop editor's "＋ Add to Album" button)
    // -----------------------------------------------------------------------

    _wireAlbumPicker() {
      this.shadowRoot.getElementById('album-picker-cancel').addEventListener('click', () => this._closeAlbumPicker());
      this.shadowRoot.getElementById('album-picker-save').addEventListener('click', () => this._saveAlbumPicker());
    }

    async _openAlbumPicker(image) {
      // A pending auto-close from a previous save (see _saveAlbumPicker)
      // must not fire against whatever gets opened next.
      if (this._albumPickerCloseTimer) {
        clearTimeout(this._albumPickerCloseTimer);
        this._albumPickerCloseTimer = null;
      }
      await this._loadAlbums();
      this._albumPickerImage = image;

      const overlay      = this.shadowRoot.getElementById('album-picker-overlay');
      const list          = this.shadowRoot.getElementById('album-picker-list');
      const newNameInput = this.shadowRoot.getElementById('album-picker-new-name');
      const fb            = this.shadowRoot.getElementById('album-picker-fb');

      const current = new Set(image.albums && image.albums.length ? image.albums : [DEFAULT_ALBUM]);
      // Union of every known album with whatever this image already carries
      // (covers an album that, for whatever reason, only lives on this image).
      const names = new Set(this._albums.map(a => a.name));
      current.forEach(n => names.add(n));

      list.innerHTML = [...names]
        .sort((a, b) => (a === DEFAULT_ALBUM ? -1 : b === DEFAULT_ALBUM ? 1 : a.localeCompare(b)))
        .map(name => `
          <label>
            <input type="checkbox" value="${this._esc(name)}" ${current.has(name) ? 'checked' : ''}>
            ${this._esc(name)}
          </label>
        `).join('');

      newNameInput.value = '';
      fb.style.display = 'none';
      overlay.style.display = 'flex';
    }

    _closeAlbumPicker() {
      if (this._albumPickerCloseTimer) {
        clearTimeout(this._albumPickerCloseTimer);
        this._albumPickerCloseTimer = null;
      }
      this.shadowRoot.getElementById('album-picker-overlay').style.display = 'none';
      this._albumPickerImage = null;
    }

    async _saveAlbumPicker() {
      const image = this._albumPickerImage;
      if (!image) return;

      const list          = this.shadowRoot.getElementById('album-picker-list');
      const newNameInput = this.shadowRoot.getElementById('album-picker-new-name');
      const fb            = this.shadowRoot.getElementById('album-picker-fb');
      const saveBtn       = this.shadowRoot.getElementById('album-picker-save');

      const checked = [...list.querySelectorAll('input[type="checkbox"]:checked')].map(cb => cb.value);
      const newName = newNameInput.value.trim();
      if (newName) checked.push(newName);

      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';

      try {
        const resp = await fetch(`/api/fraimic/library/image/${image.image_id}/albums`, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ albums: checked }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        image.albums = result.image.albums;
        const libImg = this._library.find(i => i.image_id === image.image_id);
        if (libImg) libImg.albums = result.image.albums;

        await this._loadAlbums();
        // If we're viewing an album this photo just left, drop it from the grid.
        if (this._currentAlbum && !result.image.albums.includes(this._currentAlbum)) {
          this._library = this._library.filter(i => i.image_id !== image.image_id);
        }
        this._renderLibrary();

        // Show success in the picker's own feedback element -- this may be
        // opened directly from a library card with no editor open, so
        // relying on the editor's feedback element (as before) meant the
        // confirmation silently landed in a hidden part of the DOM.
        fb.className = 'feedback ok';
        fb.textContent = '✓ Albums updated';
        fb.style.display = 'block';
        // Only close if this is still the same picker session -- a fast
        // Cancel + reopen-for-a-different-photo within this window must not
        // have the wrong session slammed shut out from under it.
        this._albumPickerCloseTimer = setTimeout(() => {
          this._albumPickerCloseTimer = null;
          if (this._albumPickerImage && this._albumPickerImage.image_id === image.image_id) {
            this._closeAlbumPicker();
          }
        }, 700);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't update albums: ${err.message}`;
        fb.style.display = 'block';
      }

      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }

    // -----------------------------------------------------------------------
    // Create Album: name a new album and multi-select photos into it.
    // -----------------------------------------------------------------------

    _wireAlbumCreate() {
      this.shadowRoot.getElementById('album-create-cancel').addEventListener('click', () => {
        // Distinct from _closeAlbumCreateModal() also being called on
        // successful completion -- only an explicit Cancel click should
        // tell an in-flight save not to navigate the panel afterward.
        this._albumCreateCancelled = true;
        this._closeAlbumCreateModal();
      });
      this.shadowRoot.getElementById('album-create-save').addEventListener('click', () => this._saveAlbumCreate());
    }

    async _openAlbumCreateModal() {
      const overlay   = this.shadowRoot.getElementById('album-create-overlay');
      const nameInput = this.shadowRoot.getElementById('album-create-name');
      const grid       = this.shadowRoot.getElementById('album-create-images');
      const fb         = this.shadowRoot.getElementById('album-create-fb');

      nameInput.value = '';
      fb.style.display = 'none';
      this._albumCreateSelected = new Set();
      this._albumCreateCancelled = false;

      grid.innerHTML = '<div class="modal-file-summary">Loading photos…</div>';

      let images = [];
      try {
        const resp = await fetch('/api/fraimic/library/list', { headers: this._authHeaders() });
        const result = await resp.json();
        images = result.images || [];
      } catch (err) {
        console.warn('[fraimic-panel] library load for create-album failed:', err);
      }

      if (!images.length) {
        grid.innerHTML = '<div class="modal-file-summary">No photos in the library yet.</div>';
      } else {
        grid.innerHTML = '';
        for (const image of images) {
          const cell = document.createElement('div');
          cell.className = 'image-picker-cell';
          cell.dataset.imageId = image.image_id;
          cell.title = image.filename;
          // The thumbnail and the check badge are siblings, not
          // parent/child -- _loadThumbnail replaces its target element's
          // innerHTML wholesale, which would wipe out the badge if it were
          // nested underneath.
          cell.innerHTML = `
            <div class="image-picker-thumb">🖼</div>
            <div class="image-picker-check">✓</div>
          `;
          this._loadThumbnail(image.image_id, cell.querySelector('.image-picker-thumb'));
          cell.addEventListener('click', () => {
            const id = cell.dataset.imageId;
            if (this._albumCreateSelected.has(id)) {
              this._albumCreateSelected.delete(id);
              cell.classList.remove('selected');
            } else {
              this._albumCreateSelected.add(id);
              cell.classList.add('selected');
            }
          });
          grid.appendChild(cell);
        }
      }

      overlay.style.display = 'flex';
    }

    _closeAlbumCreateModal() {
      this.shadowRoot.getElementById('album-create-overlay').style.display = 'none';
      this._albumCreateSelected = new Set();
    }

    async _saveAlbumCreate() {
      const nameInput = this.shadowRoot.getElementById('album-create-name');
      const fb         = this.shadowRoot.getElementById('album-create-fb');
      const saveBtn    = this.shadowRoot.getElementById('album-create-save');

      const name = nameInput.value.trim();
      if (!name) {
        fb.className = 'feedback err';
        fb.textContent = 'Enter a name for the album.';
        fb.style.display = 'block';
        return;
      }
      if (!this._albumCreateSelected.size) {
        fb.className = 'feedback err';
        fb.textContent = 'Select at least one photo.';
        fb.style.display = 'block';
        return;
      }

      this._albumCreateCancelled = false;
      saveBtn.disabled = true;
      saveBtn.textContent = 'Creating…';

      try {
        const resp = await fetch(`/api/fraimic/library/albums/${encodeURIComponent(name)}/images`, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_ids: [...this._albumCreateSelected] }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        if (this._albumCreateCancelled) {
          // User dismissed the modal while this was in flight -- the album
          // was still created server-side, just don't yank them into it.
          await this._loadAlbums();
          this._renderLibrary();
        } else {
          this._closeAlbumCreateModal();
          await this._loadAlbums();
          await this._openAlbum(name);
          if (!result.count) {
            // Every selected photo already carried this tag (e.g. the name
            // matched an existing album exactly) -- land in the album
            // since that's still accurate, just don't imply anything new
            // was added.
            const libFb = this.shadowRoot.getElementById('lib-fb');
            libFb.className = 'feedback ok';
            libFb.textContent = `"${name}" already contained every photo you selected.`;
            libFb.style.display = 'block';
            setTimeout(() => { libFb.style.display = 'none'; }, 5000);
          }
        }
      } catch (err) {
        if (!this._albumCreateCancelled) {
          fb.className = 'feedback err';
          fb.textContent = `Couldn't create album: ${err.message}`;
          fb.style.display = 'block';
        }
      }

      saveBtn.disabled = false;
      saveBtn.textContent = 'Create Album';
    }

    // -----------------------------------------------------------------------
    // Scenes: a saved (frame, image) assignment list sendable all at once.
    // -----------------------------------------------------------------------

    _wireSceneToolbar() {
      this.shadowRoot.getElementById('scene-new-btn').addEventListener('click', () => this._openSceneEditor());
    }

    async _loadScenes() {
      try {
        const resp = await fetch('/api/fraimic/scenes', { headers: this._authHeaders() });
        const result = await resp.json();
        this._scenes = result.scenes || [];
      } catch (err) {
        console.error('[fraimic-panel] scenes load failed:', err);
        this._scenes = [];
      }
    }

    // A scene from a scene pack install carries source: 'addon'; anything
    // else (including scenes saved before that field existed) is 'user'.
    _scenesInGroup(key) {
      return this._scenes.filter(scene =>
        key === 'addon' ? scene.source === 'addon' : scene.source !== 'addon'
      );
    }

    // Both groups render as sections on one screen -- no drill-in click.
    _renderScenes() {
      const grid = this.shadowRoot.getElementById('scene-grid');

      if (!this._scenes.length) {
        grid.innerHTML = `
          <div class="empty">
            <div class="empty-icon">▶</div>
            <h2>No scenes yet</h2>
            <p>Pick an album, match its photos to frames, then send them all to
               your wall at once — e.g. four frames showing "1", "2", "3", "4" in order.</p>
          </div>
        `;
        return;
      }

      const userScenes  = this._scenesInGroup('user');
      const addonScenes = this._scenesInGroup('addon');

      grid.innerHTML = '';

      grid.appendChild(this._buildSectionHeader('👤 User Generated Scenes'));
      if (userScenes.length) {
        for (const scene of userScenes) grid.appendChild(this._buildSceneCard(scene));
      } else {
        grid.appendChild(this._buildSectionEmpty(
          '▶', 'No user-generated scenes yet',
          'Pick an album, match its photos to frames, then send them all to your wall at once — e.g. four frames showing "1", "2", "3", "4" in order.'
        ));
      }

      grid.appendChild(this._buildSectionHeader('🧩 Add-on Scenes'));
      if (addonScenes.length) {
        for (const scene of addonScenes) grid.appendChild(this._buildSceneCard(scene));
      } else {
        grid.appendChild(this._buildSectionEmpty(
          '🧩', 'No Add-on scenes yet',
          'Install a scene pack from the Add-ons tab to get one automatically.'
        ));
      }
    }

    _buildSceneCard(scene) {
      const el = document.createElement('div');
      el.className = 'card scene-card';
      const sid = this._sid(scene.scene_id);
      const count = Object.keys(scene.mappings || {}).length;
      const albumNote = scene.album ? `${this._esc(scene.album)} · ` : '';
      const coverImageId = Object.values(scene.mappings || {})[0];

      el.innerHTML = `
        <div class="lib-thumb" id="scene-thumb-${sid}">
          <div style="font-size:32px;text-align:center;padding:30px 0">🖼</div>
        </div>
        <div class="scene-card-title">${this._esc(scene.name)}</div>
        <div class="scene-card-summary">${albumNote}${count} frame${count === 1 ? '' : 's'}</div>
        <div class="btns" style="margin-top:10px">
          <button class="btn-primary" id="scene-send-${sid}">▶ Send Scene</button>
          <button class="btn-ghost" id="scene-edit-${sid}">✎ Edit</button>
          <button class="btn-ghost" id="scene-delete-${sid}">🗑</button>
        </div>
        <div class="feedback" id="scene-card-fb-${sid}"></div>
      `;

      if (coverImageId) {
        this._loadThumbnail(coverImageId, el.querySelector(`#scene-thumb-${sid}`));
      }

      el.querySelector(`#scene-send-${sid}`).addEventListener('click', () => this._sendScene(scene, el, sid));
      el.querySelector(`#scene-edit-${sid}`).addEventListener('click', () => this._openSceneEditor(scene));
      el.querySelector(`#scene-delete-${sid}`).addEventListener('click', () => this._deleteScene(scene));

      return el;
    }

    _wireSceneEditor() {
      this.shadowRoot.getElementById('scene-editor-cancel').addEventListener('click', () => this._closeSceneEditor());
      this.shadowRoot.getElementById('scene-editor-save').addEventListener('click', () => this._saveSceneEditor());
    }

    async _openSceneEditor(scene) {
      this._sceneEditorId = scene ? scene.scene_id : null;

      const overlay     = this.shadowRoot.getElementById('scene-editor-overlay');
      const title       = this.shadowRoot.getElementById('scene-editor-title');
      const nameInput   = this.shadowRoot.getElementById('scene-editor-name');
      const albumSelect = this.shadowRoot.getElementById('scene-editor-album');
      const fb          = this.shadowRoot.getElementById('scene-editor-fb');

      title.textContent = scene ? 'Edit Scene' : 'New Scene';
      nameInput.value = scene ? scene.name : '';
      fb.style.display = 'none';

      if (!this._albums || !this._albums.length) await this._loadAlbums();

      const existingMappings = (scene && scene.mappings) || {};
      const defaultAlbum = (scene && scene.album && this._albums.some(a => a.name === scene.album))
        ? scene.album
        : (this._albums[0] ? this._albums[0].name : DEFAULT_ALBUM);

      albumSelect.innerHTML = this._albums.map(a =>
        `<option value="${this._esc(a.name)}">${this._esc(a.name)}</option>`
      ).join('');
      albumSelect.value = defaultAlbum;
      // Switching album mid-edit invalidates the old mappings (different
      // images), so it's assigned via .onchange (overwritten every open,
      // never stacked) rather than addEventListener.
      albumSelect.onchange = () => this._renderSceneMappingRows(albumSelect.value, {});

      await this._renderSceneMappingRows(defaultAlbum, existingMappings);

      overlay.style.display = 'flex';
    }

    async _renderSceneMappingRows(albumName, existingMappings) {
      const mappingsEl = this.shadowRoot.getElementById('scene-editor-mappings');

      let images = [];
      try {
        const resp = await fetch(`/api/fraimic/library/list?album=${encodeURIComponent(albumName)}`, {
          headers: this._authHeaders(),
        });
        const result = await resp.json();
        images = result.images || [];
      } catch (err) {
        console.warn('[fraimic-panel] library load for scene editor failed:', err);
      }

      if (!images.length) {
        mappingsEl.innerHTML = `
          <p style="font-size:13px;color:var(--secondary-text-color);margin:6px 0">
            No photos in this album yet.
          </p>
        `;
        return;
      }

      mappingsEl.innerHTML = images.map(img => {
        const rid = this._sid(img.image_id);
        const assignedEntryId = Object.keys(existingMappings)
          .find(entryId => existingMappings[entryId] === img.image_id) || '';
        return `
          <div class="scene-mapping-row" data-image-id="${this._esc(img.image_id)}"
               data-initial-entry-id="${this._esc(assignedEntryId)}">
            <div class="scene-mapping-thumb" id="scene-map-thumb-${rid}">🖼</div>
            <div class="scene-mapping-frame">${this._esc(img.filename)}</div>
            <select class="scene-mapping-select" id="scene-map-select-${rid}"></select>
          </div>
        `;
      }).join('');

      for (const img of images) {
        const rid = this._sid(img.image_id);
        this._loadThumbnail(img.image_id, mappingsEl.querySelector(`#scene-map-thumb-${rid}`));
        const select = mappingsEl.querySelector(`#scene-map-select-${rid}`);
        select.addEventListener('change', () => {
          select.dataset.touched = '1';
          this._updateSceneFrameOptions();
        });
      }

      this._updateSceneFrameOptions();
    }

    // Rebuilds every row's frame <select> options so a frame already claimed
    // by another image in this scene can't be picked twice -- each select
    // only ever offers frames that are free, plus whichever frame it already
    // has selected.
    _updateSceneFrameOptions() {
      const mappingsEl = this.shadowRoot.getElementById('scene-editor-mappings');
      const rows = [...mappingsEl.querySelectorAll('.scene-mapping-row')];

      const current = rows.map(row => {
        const select = row.querySelector('.scene-mapping-select');
        return select.dataset.touched === '1' ? select.value : row.dataset.initialEntryId;
      });
      const used = new Set(current.filter(Boolean));

      rows.forEach((row, i) => {
        const select = row.querySelector('.scene-mapping-select');
        const own = current[i];
        const options = ['<option value="">— none —</option>'].concat(
          this._frames
            .filter(f => f.entryId === own || !used.has(f.entryId))
            .map(f => `<option value="${this._esc(f.entryId)}">${this._esc(f.title)}</option>`)
        );
        select.innerHTML = options.join('');
        select.value = own;
      });
    }

    _closeSceneEditor() {
      this.shadowRoot.getElementById('scene-editor-overlay').style.display = 'none';
      this._sceneEditorId = null;
    }

    async _saveSceneEditor() {
      const nameInput   = this.shadowRoot.getElementById('scene-editor-name');
      const albumSelect = this.shadowRoot.getElementById('scene-editor-album');
      const mappingsEl  = this.shadowRoot.getElementById('scene-editor-mappings');
      const fb          = this.shadowRoot.getElementById('scene-editor-fb');
      const saveBtn     = this.shadowRoot.getElementById('scene-editor-save');

      const name = nameInput.value.trim();
      if (!name) {
        fb.className = 'feedback err';
        fb.textContent = 'Enter a name for the scene.';
        fb.style.display = 'block';
        return;
      }

      const mappings = {};
      mappingsEl.querySelectorAll('.scene-mapping-row').forEach(row => {
        const select = row.querySelector('.scene-mapping-select');
        if (select && select.value) mappings[select.value] = row.dataset.imageId;
      });
      if (!Object.keys(mappings).length) {
        fb.className = 'feedback err';
        fb.textContent = 'Assign a frame to at least one image.';
        fb.style.display = 'block';
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';

      try {
        const url = this._sceneEditorId
          ? `/api/fraimic/scenes/${this._sceneEditorId}`
          : '/api/fraimic/scenes';
        const resp = await fetch(url, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, mappings, album: albumSelect.value }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        this._closeSceneEditor();
        await this._loadScenes();
        this._renderScenes();
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't save scene: ${err.message}`;
        fb.style.display = 'block';
      }

      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Scene';
    }

    async _sendScene(scene, el, sid) {
      const btn = el.querySelector(`#scene-send-${sid}`);
      const fb  = el.querySelector(`#scene-card-fb-${sid}`);
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Sending…';

      try {
        const resp = await fetch(`/api/fraimic/scenes/${scene.scene_id}/send`, {
          method: 'POST', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        const results = result.results || [];
        const ok = results.filter(r => r.success).length;
        const failed = results.filter(r => !r.success);

        if (ok) {
          let changed = false;
          for (const r of results) {
            if (!r.success) continue;
            const imageId = scene.mappings[r.entry_id];
            const frame = this._frames.find(f => f.entryId === r.entry_id);
            if (frame && imageId) {
              frame.lastImageId = imageId;
              changed = true;
            }
          }
          if (changed) this._renderFrames();
        }

        if (resp.ok && ok === results.length && results.length) {
          fb.className = 'feedback ok';
          fb.textContent = `✓ Sent to ${ok} frame${ok === 1 ? '' : 's'}`;
        } else if (ok) {
          fb.className = 'feedback err';
          fb.textContent = `Sent to ${ok}/${results.length} frames — failed: `
            + failed.map(f => f.message || f.entry_id).join(', ');
        } else {
          fb.className = 'feedback err';
          fb.textContent = `Send failed: ${(failed[0] && failed[0].message) || result.message || resp.statusText || resp.status}`;
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';

      btn.disabled = false;
      btn.textContent = prevText;
      setTimeout(() => { fb.style.display = 'none'; }, 6000);
    }

    async _deleteScene(scene) {
      if (!window.confirm(`Delete scene "${scene.name}"? This can't be undone.`)) return;

      const fb = this.shadowRoot.getElementById('scene-fb');
      try {
        const resp = await fetch(`/api/fraimic/scenes/${scene.scene_id}`, {
          method: 'DELETE', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (resp.ok && result.success) {
          await this._loadScenes();
          this._renderScenes();
          return;
        }
        fb.className = 'feedback err';
        fb.textContent = `Delete failed: ${result.message || resp.statusText || resp.status}`;
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Network error: ${err.message}`;
      }
      fb.style.display = 'block';
    }

    // -----------------------------------------------------------------------
    // Walls -- a virtual layout of a subset of the user's frames, positioned
    // the way they're physically hung. Pure panel-local state: a wall only
    // stores where each frame sits on a free-form canvas, never which image
    // it shows. Loading a scene onto a wall and saving back is done entirely
    // against the existing scenes API -- see _saveWallToScene.
    // -----------------------------------------------------------------------

    _wireFramesSubnav() {
      this.shadowRoot.querySelectorAll('.subnav-btn').forEach(btn => {
        btn.addEventListener('click', () => this._setFramesSub(btn.dataset.framesub));
      });
    }

    _setFramesSub(name) {
      this._framesSub = name;
      const root = this.shadowRoot;
      ['status', 'walls'].forEach(sub => {
        const content = root.getElementById(`frames-sub-${sub}`);
        const btn     = root.querySelector(`.subnav-btn[data-framesub="${sub}"]`);
        if (content) content.classList.toggle('active', sub === name);
        if (btn)     btn.classList.toggle('active', sub === name);
      });
    }

    _wireWallToolbar() {
      this.shadowRoot.getElementById('wall-select').addEventListener('change', (e) => {
        const nextId = e.target.value || null;
        if (this._wallLayoutIsDirty() && !window.confirm(
          'You have unsaved layout changes on this wall. Switch walls and discard them?'
        )) {
          e.target.value = this._activeWallId || '';
          return;
        }
        this._openWall(nextId);
      });
      this.shadowRoot.getElementById('wall-new-btn').addEventListener('click', () => this._createWall());
      this.shadowRoot.getElementById('wall-delete-btn').addEventListener('click', () => this._deleteWall());
      this.shadowRoot.getElementById('wall-save-layout-btn').addEventListener('click', () => this._saveWallLayout());
      this.shadowRoot.getElementById('wall-scene-select').addEventListener('change', (e) => {
        this._loadSceneOntoWall(e.target.value || null);
      });
      this.shadowRoot.getElementById('wall-save-scene-btn').addEventListener('click', () => this._saveWallToScene());
      this.shadowRoot.getElementById('wall-save-new-scene-btn').addEventListener('click', () => this._saveWallAsNewScene());
    }

    async _loadWalls() {
      try {
        const resp = await fetch('/api/fraimic/walls', { headers: this._authHeaders() });
        const result = await resp.json();
        this._walls = result.walls || [];
      } catch (err) {
        console.error('[fraimic-panel] walls load failed:', err);
        this._walls = [];
      }
    }

    _renderWallsSubview() {
      const select = this.shadowRoot.getElementById('wall-select');
      select.innerHTML = '<option value="">— Select a wall —</option>' +
        this._walls.map(w => `<option value="${this._esc(w.wall_id)}">${this._esc(w.name)}</option>`).join('');
      select.value = this._activeWallId || '';

      const hasActive = !!(this._activeWallId && this._walls.some(w => w.wall_id === this._activeWallId));
      this.shadowRoot.getElementById('wall-delete-btn').style.display = hasActive ? '' : 'none';
      this.shadowRoot.getElementById('wall-empty').style.display = hasActive ? 'none' : '';
      this.shadowRoot.getElementById('wall-editor').style.display = hasActive ? '' : 'none';

      if (hasActive) {
        this._renderWallScenePicker();
        this._renderWallCanvas();
      }
    }

    // Whether the working copy of the active wall's placements (mutated by
    // dragging tiles) has diverged from what's actually persisted -- used to
    // warn before switching walls silently discards unsaved drag edits.
    _wallLayoutIsDirty() {
      if (!this._activeWallId) return false;
      const wall = this._walls.find(w => w.wall_id === this._activeWallId);
      if (!wall) return false;
      return JSON.stringify(wall.placements || {}) !== JSON.stringify(this._wallPlacements || {});
    }

    _openWall(wallId) {
      this._activeWallId = wallId || null;
      const wall = wallId && this._walls.find(w => w.wall_id === wallId);
      // Deep-copy so canvas edits don't mutate this._walls until Save Layout.
      this._wallPlacements = wall ? JSON.parse(JSON.stringify(wall.placements || {})) : {};
      this._wallActiveSceneId = null;
      this._wallPendingMappings = {};
      this._wallPendingPickAlbum = {};
      this._renderWallsSubview();
    }

    async _createWall() {
      const name = window.prompt('Name this wall (e.g. "Living Room"):');
      if (!name || !name.trim()) return;

      const fb = this.shadowRoot.getElementById('wall-fb');
      try {
        const resp = await fetch('/api/fraimic/walls', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name.trim(), placements: {} }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        fb.style.display = 'none';
        await this._loadWalls();
        this._openWall(result.wall.wall_id);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't create wall: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    async _deleteWall() {
      const wall = this._walls.find(w => w.wall_id === this._activeWallId);
      if (!wall) return;
      if (!window.confirm(`Delete wall "${wall.name}"? This can't be undone.`)) return;

      const fb = this.shadowRoot.getElementById('wall-fb');
      try {
        const resp = await fetch(`/api/fraimic/walls/${wall.wall_id}`, {
          method: 'DELETE', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Delete failed: ${err.message}`;
        fb.style.display = 'block';
        return;
      }
      await this._loadWalls();
      this._openWall(null);
    }

    // A frame tile's on-canvas size, aspect-ratio-correct for that frame's
    // real resolution (orientation-swapped if the frame is orientation-
    // locked) -- normalized to a fixed longest edge so every tile reads
    // clearly regardless of the frame's actual native resolution.
    _wallTileDims(frame) {
      let w = (frame && frame.width) || 1200;
      let h = (frame && frame.height) || 1600;
      const orientation = frame && frame.orientation;
      if (orientation === 'portrait' && w > h) { const t = w; w = h; h = t; }
      if (orientation === 'landscape' && h > w) { const t = w; w = h; h = t; }
      const targetLongest = 140;
      const scale = targetLongest / Math.max(w, h);
      return { width: Math.round(w * scale), height: Math.round(h * scale) };
    }

    _renderWallCanvas() {
      const palette = this.shadowRoot.getElementById('wall-palette');
      const canvas  = this.shadowRoot.getElementById('wall-canvas');

      const placedEntryIds = new Set(Object.keys(this._wallPlacements));
      const unplaced = this._frames.filter(f => !placedEntryIds.has(f.entryId));

      palette.innerHTML = '';
      if (!unplaced.length) {
        palette.innerHTML = '<div style="font-size:12px;color:var(--secondary-text-color);padding:6px">All frames placed.</div>';
      } else {
        for (const frame of unplaced) {
          const item = document.createElement('div');
          item.className = 'wall-palette-item';
          item.dataset.entryId = frame.entryId;
          item.textContent = frame.title;
          item.addEventListener('pointerdown', (e) => this._wallBeginDrag(e, frame.entryId, 'palette'));
          palette.appendChild(item);
        }
      }

      canvas.innerHTML = '';
      for (const entryId of Object.keys(this._wallPlacements)) {
        const frame = this._frames.find(f => f.entryId === entryId);
        if (!frame) continue; // frame removed/reconfigured since this wall was laid out
        const pos  = this._wallPlacements[entryId];
        const dims = this._wallTileDims(frame);

        const tile = document.createElement('div');
        tile.className = 'wall-tile';
        tile.dataset.entryId = entryId;
        tile.style.left   = `${pos.x}px`;
        tile.style.top    = `${pos.y}px`;
        tile.style.width  = `${dims.width}px`;
        tile.style.height = `${dims.height}px`;
        tile.title = frame.title;
        canvas.appendChild(tile);

        this._renderWallTileContent(tile, entryId, frame);
        tile.addEventListener('pointerdown', (e) => this._wallBeginDrag(e, entryId, 'tile'));
      }

      this._updateWallSaveToSceneAvailability();
    }

    // Keeps the Save to Scene button (and the explanatory hint above it) in
    // sync with the album lock -- called after every wall canvas render, the
    // same "re-render everything downstream of a state change" pattern
    // _updateSceneFrameOptions uses for the Scenes tab editor.
    _updateWallSaveToSceneAvailability() {
      const btn  = this.shadowRoot.getElementById('wall-save-scene-btn');
      const hint = this.shadowRoot.getElementById('wall-lock-hint');
      const lockedAlbum = this._wallSceneAlbumLock();

      if (!lockedAlbum) {
        btn.disabled = false;
        btn.title = '';
        hint.style.display = 'none';
        return;
      }

      const violated = this._wallHasOffAlbumPick();
      btn.disabled = violated;
      hint.style.display = 'block';
      if (violated) {
        hint.className = 'wall-lock-hint warn';
        hint.textContent = `Save to Scene is off -- this add-on scene is locked to the "${lockedAlbum}" album ` +
          `and at least one pick here comes from elsewhere. Use Save As New Scene to keep it, or re-pick from ` +
          `"${lockedAlbum}" to re-enable saving back to the original.`;
        btn.title = `Locked to the "${lockedAlbum}" album`;
      } else {
        hint.className = 'wall-lock-hint';
        hint.textContent = `This is an add-on scene -- locked to the "${lockedAlbum}" album.`;
        btn.title = '';
      }
    }

    // Which image_id (if any) is currently showing on a wall tile: a pending
    // edit made this session takes priority over the active preview scene's
    // own mapping ('' means the user explicitly cleared this tile).
    _wallEffectiveMapping(entryId) {
      if (Object.prototype.hasOwnProperty.call(this._wallPendingMappings, entryId)) {
        return this._wallPendingMappings[entryId] || null;
      }
      const scene = this._wallActiveSceneId
        && this._scenes.find(s => s.scene_id === this._wallActiveSceneId);
      return (scene && scene.mappings && scene.mappings[entryId]) || null;
    }

    _renderWallTileContent(tile, entryId, frame) {
      const imageId = this._wallEffectiveMapping(entryId);
      if (!imageId) {
        tile.innerHTML = `<div>${this._esc(frame.title)}</div>`;
        return;
      }
      tile.innerHTML = '';
      // _loadThumbnail paints synchronously on a cache hit and dedupes
      // concurrent fetches, so repeated renders and same-image tiles are
      // cheap.
      this._loadThumbnail(imageId, tile);
    }

    // NOT a CSS attribute-selector lookup: this file's top-level `CSS` const
    // (the stylesheet template string, see top of file) shadows the global
    // `CSS` object everywhere in this closure, so `CSS.escape` is unavailable
    // here -- it would throw "CSS.escape is not a function".
    _wallTileEl(canvas, entryId) {
      return [...canvas.querySelectorAll('.wall-tile')].find(el => el.dataset.entryId === entryId) || null;
    }

    // Applies immediately when idle, then coalesces bursts to one style
    // write per frame -- high-rate pointer devices can deliver pointermove
    // faster than the display can paint.
    _positionWallGhost(clientX, clientY) {
      const drag = this._wallDrag;
      if (!drag) return;
      drag.lastX = clientX;
      drag.lastY = clientY;
      if (drag.raf) return; // a frame is already scheduled; it reads lastX/lastY
      this._applyWallGhost(drag);
      drag.raf = requestAnimationFrame(() => {
        drag.raf = null;
        if (this._wallDrag === drag) this._applyWallGhost(drag);
      });
    }

    _applyWallGhost(drag) {
      drag.ghost.style.left = `${drag.lastX - drag.dims.width / 2}px`;
      drag.ghost.style.top  = `${drag.lastY - drag.dims.height / 2}px`;
    }

    _wallBeginDrag(e, entryId, kind) {
      e.preventDefault();
      const canvas = this.shadowRoot.getElementById('wall-canvas');
      const frame  = this._frames.find(f => f.entryId === entryId);
      if (!frame) return;
      const dims = this._wallTileDims(frame);

      const ghost = document.createElement('div');
      ghost.className = 'wall-drag-ghost';
      ghost.style.width  = `${dims.width}px`;
      ghost.style.height = `${dims.height}px`;
      ghost.textContent = frame.title;
      this.shadowRoot.appendChild(ghost);

      let startLeft = 0, startTop = 0;
      if (kind === 'tile') {
        const tileEl = this._wallTileEl(canvas, entryId);
        if (tileEl) {
          startLeft = parseFloat(tileEl.style.left) || 0;
          startTop  = parseFloat(tileEl.style.top) || 0;
          tileEl.classList.add('dragging');
        }
      }

      this._wallDrag = {
        kind, entryId, dims, ghost,
        startClientX: e.clientX, startClientY: e.clientY,
        startLeft, startTop,
        moved: false,
      };

      this._positionWallGhost(e.clientX, e.clientY);
      // signal: if the panel is detached mid-drag, _dispose severs these.
      window.addEventListener('pointermove', this._onWallPointerMove, { signal: this._abort.signal });
      window.addEventListener('pointerup', this._onWallPointerUp, { signal: this._abort.signal });
    }

    _onWallPointerMove(e) {
      const drag = this._wallDrag;
      if (!drag) return;
      if (!drag.moved && (Math.abs(e.clientX - drag.startClientX) > 4 || Math.abs(e.clientY - drag.startClientY) > 4)) {
        drag.moved = true;
      }
      this._positionWallGhost(e.clientX, e.clientY);
    }

    _onWallPointerUp(e) {
      const drag = this._wallDrag;
      if (!drag) return;
      window.removeEventListener('pointermove', this._onWallPointerMove);
      window.removeEventListener('pointerup', this._onWallPointerUp);
      drag.ghost.remove();
      this._wallDrag = null;

      const canvas = this.shadowRoot.getElementById('wall-canvas');
      const tileEl = this._wallTileEl(canvas, drag.entryId);
      if (tileEl) tileEl.classList.remove('dragging');

      if (drag.kind === 'tile' && !drag.moved) {
        // A click, not a drag -- open the image picker for this tile
        // instead of "repositioning" it to the same spot.
        this._openWallImagePicker(drag.entryId);
        return;
      }

      const canvasRect = canvas.getBoundingClientRect();

      if (drag.kind === 'palette') {
        const withinCanvas = e.clientX >= canvasRect.left && e.clientX <= canvasRect.right
          && e.clientY >= canvasRect.top && e.clientY <= canvasRect.bottom;
        if (!withinCanvas) {
          // Dropped outside the wall -- treat as a cancel rather than
          // snapping it onto whichever edge happens to be nearest.
          this._renderWallCanvas();
          return;
        }
      }

      const rawX = drag.kind === 'palette'
        ? (e.clientX - canvasRect.left + canvas.scrollLeft - drag.dims.width / 2)
        : (drag.startLeft + (e.clientX - drag.startClientX));
      const rawY = drag.kind === 'palette'
        ? (e.clientY - canvasRect.top + canvas.scrollTop - drag.dims.height / 2)
        : (drag.startTop + (e.clientY - drag.startClientY));

      const GRID = 20;
      const x = Math.max(0, Math.round(rawX / GRID) * GRID);
      const y = Math.max(0, Math.round(rawY / GRID) * GRID);

      this._wallPlacements[drag.entryId] = { x, y };
      if (drag.kind === 'tile' && tileEl) {
        // Repositioning changes nothing structural (same tiles, same
        // palette, same mappings) -- move the one tile in place instead of
        // tearing down and rebuilding the whole canvas.
        tileEl.style.left = `${x}px`;
        tileEl.style.top  = `${y}px`;
      } else {
        this._renderWallCanvas();
      }
    }

    async _saveWallLayout() {
      const fb  = this.shadowRoot.getElementById('wall-fb');
      const btn = this.shadowRoot.getElementById('wall-save-layout-btn');

      const wall = this._walls.find(w => w.wall_id === this._activeWallId);
      if (!wall) {
        // Previously silent -- e.g. this wall was deleted from another tab
        // since it was opened here. A no-op click with no feedback reads as
        // "Save Layout doesn't do anything", so surface it instead.
        fb.className = 'feedback err';
        fb.textContent = "Couldn't save layout: this wall is no longer available. Pick a wall again.";
        fb.style.display = 'block';
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        const resp = await fetch(`/api/fraimic/walls/${wall.wall_id}`, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: wall.name, placements: this._wallPlacements }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        await this._loadWalls();
        fb.className = 'feedback ok';
        fb.textContent = 'Layout saved.';
        fb.style.display = 'block';
        setTimeout(() => { fb.style.display = 'none'; }, 3000);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't save layout: ${err.message}`;
        fb.style.display = 'block';
      }
      btn.disabled = false;
      btn.textContent = 'Save Layout';
    }

    _renderWallScenePicker() {
      const select = this.shadowRoot.getElementById('wall-scene-select');
      select.innerHTML = '<option value="">— None —</option>' +
        this._scenes.map(s => `<option value="${this._esc(s.scene_id)}">${this._esc(s.name)}</option>`).join('');
      select.value = this._wallActiveSceneId || '';
    }

    _loadSceneOntoWall(sceneId) {
      this._wallActiveSceneId = sceneId || null;
      this._wallPendingMappings = {};
      this._wallPendingPickAlbum = {};
      this._renderWallCanvas();
    }

    // An add-on scene ships bound to the album its images were installed
    // into (see ScenePackManager -- every pack image is uploaded into, and
    // the pack's auto-built scene is scoped to, the same album). User-made
    // scenes have no such binding -- picking images from any album for any
    // frame is the whole point of building a scene by hand. Returns the
    // locked album name, or null when no lock applies.
    _wallSceneAlbumLock() {
      const scene = this._wallActiveSceneId && this._scenes.find(s => s.scene_id === this._wallActiveSceneId);
      return (scene && scene.source === 'addon' && scene.album) || null;
    }

    // True once any *currently pending* image pick was made while the
    // picker's album filter was set away from the scene's locked album --
    // this is what disables Save to Scene (Save As New Scene is never
    // affected, since forking into a user-owned scene is always allowed).
    // Clearing a tile's image doesn't count -- only actually picking an
    // off-album image does.
    _wallHasOffAlbumPick() {
      const lockedAlbum = this._wallSceneAlbumLock();
      if (!lockedAlbum) return false;
      return Object.keys(this._wallPendingMappings).some(entryId =>
        this._wallPendingMappings[entryId] && this._wallPendingPickAlbum[entryId] !== lockedAlbum
      );
    }

    _wireWallImagePicker() {
      this.shadowRoot.getElementById('wall-image-picker-cancel').addEventListener('click', () => this._closeWallImagePicker());
      this.shadowRoot.getElementById('wall-image-picker-clear').addEventListener('click', () => {
        if (!this._wallImagePickerEntryId) return;
        this._wallPendingMappings[this._wallImagePickerEntryId] = '';
        this._closeWallImagePicker();
        this._renderWallCanvas();
      });
      this.shadowRoot.getElementById('wall-image-picker-album').addEventListener('change', () => this._loadWallImagePickerImages());
      // Clicking the transparent backdrop (not the panel itself) closes the
      // picker -- e.target is only the overlay element when the click lands
      // outside .wall-picker-box, same as a normal modal's "click outside
      // to dismiss", just without a darkened background.
      this.shadowRoot.getElementById('wall-image-picker-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'wall-image-picker-overlay') this._closeWallImagePicker();
      });
      this._wireWallImagePickerDrag();
    }

    // Lets the picker panel be dragged by its header so the wall canvas
    // behind it stays reachable while choosing an image -- see the
    // .wall-picker-overlay/.wall-picker-box CSS comment for why this isn't a
    // centered modal-overlay like the rest of the panel's modals.
    _wireWallImagePickerDrag() {
      const header = this.shadowRoot.getElementById('wall-image-picker-header');
      const box    = this.shadowRoot.getElementById('wall-image-picker-box');

      header.addEventListener('pointerdown', (e) => {
        if (e.target.closest('button')) return; // don't hijack the close button
        e.preventDefault();

        const rect = box.getBoundingClientRect();
        // Switch from the CSS-centered default (left:50%+transform) to
        // absolute pixel positioning so the drag math below is a simple
        // delta -- and so the panel stays wherever it's dropped instead of
        // re-centering on the next open.
        box.style.left = `${rect.left}px`;
        box.style.top  = `${rect.top}px`;
        box.style.transform = 'none';
        header.classList.add('dragging');

        const startClientX = e.clientX, startClientY = e.clientY;
        const startLeft = rect.left, startTop = rect.top;

        // Coalesce style writes to one per frame (see _positionWallGhost).
        let lastX = e.clientX, lastY = e.clientY, raf = null;
        const apply = () => {
          box.style.left = `${startLeft + (lastX - startClientX)}px`;
          box.style.top  = `${startTop + (lastY - startClientY)}px`;
        };
        const onMove = (ev) => {
          lastX = ev.clientX;
          lastY = ev.clientY;
          if (raf) return;
          apply();
          raf = requestAnimationFrame(() => { raf = null; apply(); });
        };
        const onUp = () => {
          header.classList.remove('dragging');
          if (raf) { cancelAnimationFrame(raf); raf = null; }
          apply(); // land exactly on the final pointer position
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
        };
        // signal: if the panel is detached mid-drag, _dispose severs these.
        window.addEventListener('pointermove', onMove, { signal: this._abort.signal });
        window.addEventListener('pointerup', onUp, { signal: this._abort.signal });
      });
    }

    async _openWallImagePicker(entryId) {
      this._wallImagePickerEntryId = entryId;

      const overlay     = this.shadowRoot.getElementById('wall-image-picker-overlay');
      const albumSelect = this.shadowRoot.getElementById('wall-image-picker-album');
      const fb          = this.shadowRoot.getElementById('wall-image-picker-fb');
      fb.style.display = 'none';

      if (!this._albums || !this._albums.length) await this._loadAlbums();
      albumSelect.innerHTML = '<option value="">All Photos</option>' +
        this._albums.map(a => `<option value="${this._esc(a.name)}">${this._esc(a.name)}</option>`).join('');
      // An add-on scene's images all ship in one dedicated album -- default
      // straight to it instead of "All Photos" so picking a replacement for
      // one of its frames doesn't require hunting it down manually. A
      // user-made scene has no such album, so this is a no-op for those.
      const lockedAlbum = this._wallSceneAlbumLock();
      albumSelect.value = lockedAlbum || '';

      overlay.style.display = 'block';
      await this._loadWallImagePickerImages();
    }

    // Separated from _openWallImagePicker so the album <select> can re-run
    // just this part without resetting the panel's dragged position or
    // reloading the album list.
    async _loadWallImagePickerImages() {
      const entryId = this._wallImagePickerEntryId;
      // A token, not just entryId, guards against a slow fetch from an
      // earlier open/album-change finishing after the user moved on --
      // without this, a stale response could render a grid whose click
      // handlers still assign to the wrong entryId or the wrong album filter.
      const token = (this._wallImagePickerToken = (this._wallImagePickerToken || 0) + 1);

      const grid        = this.shadowRoot.getElementById('wall-image-picker-grid');
      const albumSelect = this.shadowRoot.getElementById('wall-image-picker-album');
      const album       = albumSelect.value;
      grid.innerHTML = '<div class="modal-file-summary">Loading photos…</div>';

      const lockedAlbum = this._wallSceneAlbumLock();
      const hint = this.shadowRoot.getElementById('wall-image-picker-lock-hint');
      if (!lockedAlbum) {
        hint.style.display = 'none';
      } else if (album === lockedAlbum) {
        hint.className = 'wall-lock-hint';
        hint.textContent = `This is an add-on scene -- locked to the "${lockedAlbum}" album.`;
        hint.style.display = 'block';
      } else {
        hint.className = 'wall-lock-hint warn';
        hint.textContent = `Picking outside "${lockedAlbum}" will disable Save to Scene for this session -- ` +
          `you can still use Save As New Scene.`;
        hint.style.display = 'block';
      }

      let images = [];
      try {
        const url = album
          ? `/api/fraimic/library/list?album=${encodeURIComponent(album)}`
          : '/api/fraimic/library/list';
        const resp = await fetch(url, { headers: this._authHeaders() });
        const result = await resp.json();
        images = result.images || [];
      } catch (err) {
        console.warn('[fraimic-panel] library load for wall image picker failed:', err);
      }

      if (token !== this._wallImagePickerToken) return; // superseded by a newer open/album change

      if (!images.length) {
        grid.innerHTML = album
          ? '<div class="modal-file-summary">No photos in this album yet.</div>'
          : '<div class="modal-file-summary">No photos in the library yet.</div>';
        return;
      }

      grid.innerHTML = '';
      for (const image of images) {
        const cell = document.createElement('div');
        cell.className = 'image-picker-cell';
        cell.dataset.imageId = image.image_id;
        cell.title = image.filename;
        cell.innerHTML = `<div class="image-picker-thumb">🖼</div>`;

        this._loadThumbnail(image.image_id, cell.querySelector('.image-picker-thumb'));

        cell.addEventListener('click', () => {
          this._wallPendingMappings[entryId] = image.image_id;
          // Recorded at the moment of picking, from whichever album filter
          // was active right now -- not the image's own album tags -- so
          // this stays a simple, predictable "did you leave the scene's
          // locked album to make this pick" check (see _wallHasOffAlbumPick).
          this._wallPendingPickAlbum[entryId] = album;
          this._closeWallImagePicker();
          this._renderWallCanvas();
        });
        grid.appendChild(cell);
      }
    }

    _closeWallImagePicker() {
      this.shadowRoot.getElementById('wall-image-picker-overlay').style.display = 'none';
      this._wallImagePickerEntryId = null;
    }

    // Merges this wall's tile assignments into the scene's *current* full
    // mappings -- a scene can span multiple walls, so this must never
    // clobber mappings for frames that aren't placed on this one.
    async _saveWallToScene() {
      const fb = this.shadowRoot.getElementById('wall-scene-fb');
      if (!this._wallActiveSceneId) {
        fb.className = 'feedback err';
        fb.textContent = 'Load a scene first.';
        fb.style.display = 'block';
        return;
      }
      // The button is already disabled for this -- this is a backstop, not
      // the primary guard, in case this ever gets invoked some other way.
      if (this._wallHasOffAlbumPick()) {
        fb.className = 'feedback err';
        fb.textContent = `This add-on scene is locked to the "${this._wallSceneAlbumLock()}" album -- ` +
          'use Save As New Scene to keep a pick from outside it.';
        fb.style.display = 'block';
        return;
      }

      try {
        await this._loadScenes();
        const scene = this._scenes.find(s => s.scene_id === this._wallActiveSceneId);
        if (!scene) {
          // Don't just dead-end here -- whatever the user picked for this
          // wall's tiles (this._wallPendingMappings) is still intact, so
          // point them at "Save As New Scene" instead of discarding it.
          console.error(
            '[fraimic-panel] wall scene save: active scene not found after reload',
            { activeSceneId: this._wallActiveSceneId, availableSceneIds: this._scenes.map(s => s.scene_id) }
          );
          this._wallActiveSceneId = null;
          this._renderWallScenePicker();
          throw new Error(
            "that scene isn't available anymore (renamed or deleted elsewhere). " +
            'Your image choices are still applied here -- use "Save As New Scene" to keep them.'
          );
        }

        const mergedMappings = { ...scene.mappings };
        for (const entryId of Object.keys(this._wallPlacements)) {
          const imageId = this._wallEffectiveMapping(entryId);
          if (imageId) {
            mergedMappings[entryId] = imageId;
          } else {
            delete mergedMappings[entryId];
          }
        }

        const resp = await fetch(`/api/fraimic/scenes/${scene.scene_id}`, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: scene.name, mappings: mergedMappings, album: scene.album }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        await this._loadScenes();
        this._wallPendingMappings = {};
        this._wallPendingPickAlbum = {};
        this._renderWallCanvas();
        this._renderScenes();

        fb.className = 'feedback ok';
        fb.textContent = `Saved to scene "${scene.name}".`;
        fb.style.display = 'block';
        setTimeout(() => { fb.style.display = 'none'; }, 3000);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't save scene: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    async _saveWallAsNewScene() {
      const fb = this.shadowRoot.getElementById('wall-scene-fb');
      const name = window.prompt('Name for the new scene:');
      if (!name || !name.trim()) return;

      const mappings = {};
      for (const entryId of Object.keys(this._wallPlacements)) {
        const imageId = this._wallEffectiveMapping(entryId);
        if (imageId) mappings[entryId] = imageId;
      }
      if (!Object.keys(mappings).length) {
        fb.className = 'feedback err';
        fb.textContent = 'Assign an image to at least one frame on this wall first.';
        fb.style.display = 'block';
        return;
      }

      try {
        const resp = await fetch('/api/fraimic/scenes', {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name.trim(), mappings }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        await this._loadScenes();
        this._wallActiveSceneId = result.scene.scene_id;
        this._wallPendingMappings = {};
        this._wallPendingPickAlbum = {};
        this._renderWallScenePicker();
        this._renderWallCanvas();
        this._renderScenes();

        fb.className = 'feedback ok';
        fb.textContent = `Created scene "${result.scene.name}".`;
        fb.style.display = 'block';
        setTimeout(() => { fb.style.display = 'none'; }, 3000);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't create scene: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    // -----------------------------------------------------------------------
    // Scene packs -- curated public-domain image bundles, installable with
    // one click (downloads into the library, tags an album, builds a scene).
    // -----------------------------------------------------------------------

    async _loadScenePacks() {
      const fb = this.shadowRoot.getElementById('pack-fb');
      fb.style.display = 'none';
      try {
        const resp = await fetch('/api/fraimic/scene_packs', { headers: this._authHeaders() });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        this._scenePacks = result.packs || [];
      } catch (err) {
        console.error('[fraimic-panel] scene packs load failed:', err);
        this._scenePacks = [];
        fb.className = 'feedback err';
        fb.textContent = `Couldn't load the scene pack catalog: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    // Packs are browsed through a category tile view first (this._packCategory
    // === null) and only fan out into a flat pack grid once a tile is clicked --
    // avoids dumping every pack (art + seasonal) into one undifferentiated grid.
    _renderScenePacks() {
      const grid = this.shadowRoot.getElementById('pack-grid');
      const crumb = this.shadowRoot.getElementById('addons-crumb');

      if (!this._scenePacks.length) {
        crumb.style.display = 'none';
        grid.className = 'lib-grid';
        grid.innerHTML = `
          <div class="empty">
            <div class="empty-icon">◈</div>
            <h2>No scene packs available</h2>
            <p>Couldn't reach the scene pack catalog right now -- check your
               internet connection and reload the page.</p>
          </div>
        `;
        return;
      }

      if (!this._packCategory) {
        crumb.style.display = 'none';
        grid.className = 'category-grid';
        grid.innerHTML = '';
        for (const catId of Object.keys(PACK_CATEGORIES)) {
          const packs = this._scenePacks.filter(p => (p.category || 'art') === catId);
          if (!packs.length) continue;
          grid.appendChild(this._buildCategoryTile(catId, packs));
        }
        return;
      }

      const catInfo = PACK_CATEGORIES[this._packCategory] || { label: this._packCategory };
      crumb.style.display = 'flex';
      crumb.innerHTML = `
        <button class="btn-ghost" id="addons-crumb-back">← Categories</button>
        <span class="addons-crumb-label">${this._esc(catInfo.label)}</span>
      `;
      crumb.querySelector('#addons-crumb-back').addEventListener('click', () => {
        this._packCategory = null;
        this._renderScenePacks();
      });

      grid.className = 'lib-grid';
      grid.innerHTML = '';
      for (const pack of this._scenePacks.filter(p => (p.category || 'art') === this._packCategory)) {
        grid.appendChild(this._buildPackCard(pack));
      }
    }

    _buildCategoryTile(catId, packs) {
      const info = PACK_CATEGORIES[catId] || { label: catId };
      const installedCount = packs.filter(p => p.installed).length;
      const coverUrl = `${SCENE_PACK_RAW_BASE}/${packs[0].cover}`;

      const el = document.createElement('div');
      el.className = 'card category-tile';
      el.innerHTML = `
        <img class="category-tile-cover" src="${this._esc(coverUrl)}" alt="${this._esc(info.label)}" loading="lazy">
        <div class="category-tile-overlay">
          <div class="category-tile-title">${this._esc(info.label)}</div>
          <div class="category-tile-summary">
            ${packs.length} pack${packs.length === 1 ? '' : 's'}${installedCount ? ` · ${installedCount} installed` : ''}
          </div>
        </div>
      `;
      el.addEventListener('click', () => {
        this._packCategory = catId;
        this._renderScenePacks();
      });
      return el;
    }

    _buildPackCard(pack) {
      const el = document.createElement('div');
      el.className = 'card pack-card';
      const sid = this._sid(pack.id);
      const count = (pack.images || []).length;
      const coverUrl = `${SCENE_PACK_RAW_BASE}/${pack.cover}`;
      const isWidget = pack.type === 'widget';
      const summaryText = isWidget ? 'System Add-on Widget' : `${count} image${count === 1 ? '' : 's'} · ${this._esc(pack.license || '')}`;

      let statusHtml;
      let badgeHtml = '';
      if (pack.installed) {
        if (isWidget) {
          statusHtml = `
            <button class="btn-primary" id="pack-configure-${sid}">⚙ Settings</button>
            <button class="btn-ghost" id="pack-remove-${sid}">🗑 Remove</button>
          `;
          badgeHtml = `
            <div style="margin-top:10px">
              <span class="badge-installed">✓ Configured & Active</span>
            </div>
          `;
        } else {
          statusHtml = `
            <button class="btn-ghost" id="pack-sync-${sid}" title="Re-check for missing or newly added images">🔄 Sync</button>
            <button class="btn-ghost" id="pack-remove-${sid}">🗑 Remove</button>
          `;
          badgeHtml = `
            <div style="margin-top:10px">
              <span class="badge-installed">✓ ${pack.scene_created ? 'Installed · scene created' : 'Installed'}</span>
            </div>
          `;
        }
      } else {
        statusHtml = `<button class="btn-primary" id="pack-install-${sid}">⬇ Install</button>`;
      }

      el.innerHTML = `
        <img class="pack-cover" src="${this._esc(coverUrl)}" alt="${this._esc(pack.name)}" loading="lazy" title="${isWidget ? 'Configure this add-on' : 'Preview this pack'}">
        <div class="scene-card-title">${this._esc(pack.name)}</div>
        <div class="pack-desc">${this._esc(pack.description || '')}</div>
        <div class="scene-card-summary">${summaryText}</div>
        <div class="btns" style="margin-top:10px">${statusHtml}</div>
        ${badgeHtml}
        <div class="feedback" id="pack-card-fb-${sid}"></div>
      `;

      if (!isWidget) {
        el.querySelector('.pack-cover').addEventListener('click', () => this._openPackPreview(pack, 0));
      } else {
        el.querySelector('.pack-cover').addEventListener('click', () => this._openWidgetConfigModal(pack, el, sid));
      }

      if (pack.installed) {
        if (isWidget) {
          el.querySelector(`#pack-configure-${sid}`)
            .addEventListener('click', () => this._openWidgetConfigModal(pack, el, sid));
        } else {
          el.querySelector(`#pack-sync-${sid}`)
            .addEventListener('click', () => this._syncPack(pack, el, sid));
        }
        el.querySelector(`#pack-remove-${sid}`)
          .addEventListener('click', () => this._uninstallPack(pack, el, sid));
      } else {
        el.querySelector(`#pack-install-${sid}`)
          .addEventListener('click', () => {
            if (isWidget) {
              this._openWidgetConfigModal(pack, el, sid);
            } else {
              this._installPack(pack, el, sid);
            }
          });
      }

      return el;
    }

    _openWidgetConfigModal(pack, cardEl, sid) {
      const overlay = this.shadowRoot.getElementById('widget-config-overlay');
      const title = this.shadowRoot.getElementById('widget-config-title');
      const fieldsContainer = this.shadowRoot.getElementById('widget-config-fields');
      const submitBtn = this.shadowRoot.getElementById('widget-config-submit');
      const fb = this.shadowRoot.getElementById('widget-config-fb');
      
      fb.style.display = 'none';
      title.textContent = `${pack.installed ? 'Configure' : 'Install'} ${pack.name}`;
      submitBtn.textContent = pack.installed ? 'Save Settings' : 'Install Add-on';
      
      let html = '';
      
      const frameOptions = this._frames.map(f => 
        `<option value="${f.entryId}">${this._esc(f.title)}</option>`
      ).join('');
      
      html += `
        <div class="modal-row">
          <label for="widget-config-frame">Target Frame</label>
          <select id="widget-config-frame" ${this._frames.length ? '' : 'disabled'}>
            ${this._frames.length ? frameOptions : '<option value="">No frames available</option>'}
          </select>
        </div>
      `;
      
      for (const field of (pack.config_schema || [])) {
        const fieldId = `widget-field-${field.name}`;
        const label = field.label || field.name;
        const required = field.required ? 'required' : '';
        const placeholder = field.placeholder || '';
        
        html += `
          <div class="modal-row">
            <label for="${fieldId}">${this._esc(label)}</label>
            <input type="text" id="${fieldId}" placeholder="${this._esc(placeholder)}" ${required}>
          </div>
        `;
      }
      
      html += `
        <div class="modal-row">
          <label for="widget-schedule-type">Update Schedule</label>
          <select id="widget-schedule-type">
            <option value="hourly">Hourly</option>
            <option value="daily">Daily at specific time</option>
          </select>
        </div>
        <div class="modal-row" id="widget-schedule-time-row" style="display:none">
          <label for="widget-schedule-time">Daily Update Time (24h format)</label>
          <input type="text" id="widget-schedule-time" value="07:00:00" placeholder="e.g. 07:30:00">
        </div>
      `;
      
      fieldsContainer.innerHTML = html;
      
      const schedTypeSel = this.shadowRoot.getElementById('widget-schedule-type');
      const schedTimeRow = this.shadowRoot.getElementById('widget-schedule-time-row');
      schedTypeSel.addEventListener('change', () => {
        schedTimeRow.style.display = schedTypeSel.value === 'daily' ? 'block' : 'none';
      });
      
      if (pack.installed && pack.config) {
        const config = pack.config;
        const frameSel = this.shadowRoot.getElementById('widget-config-frame');
        if (config.frame_id) frameSel.value = config.frame_id;
        
        for (const field of (pack.config_schema || [])) {
          const val = config[field.name];
          if (val !== undefined) {
            this.shadowRoot.getElementById(`widget-field-${field.name}`).value = val;
          }
        }
        
        if (config.schedule) {
          schedTypeSel.value = config.schedule.type || 'hourly';
          if (schedTypeSel.value === 'daily') {
            schedTimeRow.style.display = 'block';
            this.shadowRoot.getElementById('widget-schedule-time').value = config.schedule.time || '07:00:00';
          }
        }
      }
      
      const submitHandler = async () => {
        const frameId = this.shadowRoot.getElementById('widget-config-frame').value;
        if (!frameId) {
          fb.textContent = 'Please select a target frame.';
          fb.className = 'feedback err';
          fb.style.display = 'block';
          return;
        }
        
        const payload = {
          frame_id: frameId,
          schedule: {
            type: schedTypeSel.value,
            time: this.shadowRoot.getElementById('widget-schedule-time').value
          }
        };
        
        for (const field of (pack.config_schema || [])) {
          const val = this.shadowRoot.getElementById(`widget-field-${field.name}`).value.trim();
          if (field.required && !val) {
            fb.textContent = `Field "${field.label || field.name}" is required.`;
            fb.className = 'feedback err';
            fb.style.display = 'block';
            return;
          }
          payload[field.name] = val;
        }
        
        newSubmitBtn.disabled = true;
        newSubmitBtn.textContent = 'Saving…';
        
        try {
          const resp = await fetch(`/api/fraimic/scene_packs/${pack.id}/install`, {
            method: 'POST',
            headers: {
              ...this._authHeaders(),
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ config: payload })
          });
          const result = await resp.json().catch(() => ({}));
          if (!resp.ok || !result.success) {
            throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
          }
          
          overlay.style.display = 'none';
          
          const cardFb = cardEl.querySelector(`#pack-card-fb-${sid}`);
          cardFb.className = 'feedback ok';
          cardFb.textContent = pack.installed ? 'Settings updated!' : 'Add-on installed successfully!';
          cardFb.style.display = 'block';
          setTimeout(() => { cardFb.style.display = 'none'; }, 3000);
          
          await this._loadScenePacks();
          this._renderScenePacks();
          
        } catch (err) {
          fb.textContent = `Installation failed: ${err.message}`;
          fb.className = 'feedback err';
          fb.style.display = 'block';
          newSubmitBtn.disabled = false;
          newSubmitBtn.textContent = pack.installed ? 'Save Settings' : 'Install Add-on';
        }
      };
      
      const newSubmitBtn = submitBtn.cloneNode(true);
      submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
      newSubmitBtn.addEventListener('click', submitHandler);
      
      const cancelBtn = this.shadowRoot.getElementById('widget-config-cancel');
      const newCancelBtn = cancelBtn.cloneNode(true);
      cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
      newCancelBtn.addEventListener('click', () => {
        overlay.style.display = 'none';
      });
      
      overlay.style.display = 'flex';
    }

    async _installPack(pack, el, sid) {
      const btn = el.querySelector(`#pack-install-${sid}`);
      const fb  = el.querySelector(`#pack-card-fb-${sid}`);
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Installing…';

      try {
        const resp = await fetch(`/api/fraimic/scene_packs/${pack.id}/install`, {
          method: 'POST', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        // Rebuild every section this touches -- new album + photos in the
        // library, a new scene, and this pack's own card flipping to its
        // "installed" state -- so nothing needs a page reload.
        await this._loadAlbums();
        this._renderLibrary();
        await this._loadScenes();
        this._renderScenes();
        await this._loadScenePacks();
        this._renderScenePacks();

        // A partial install still reports success (some images did make
        // it in) -- surface it on the page-level banner rather than the
        // per-card one, since _renderScenePacks() just tore down the card
        // this callback's `fb` reference pointed at.
        if (result.errors && result.errors.length) {
          const total = result.images_added + result.errors.length;
          const pageFb = this.shadowRoot.getElementById('pack-fb');
          pageFb.className = 'feedback err';
          pageFb.textContent = `"${pack.name}" installed ${result.images_added} of ${total} images -- `
            + `failed: ${result.errors.map(e => e.filename).join(', ')}. Remove and try again, `
            + `or add the missing images to the album manually.`;
          pageFb.style.display = 'block';
        }
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Install failed: ${err.message}`;
        fb.style.display = 'block';
        btn.disabled = false;
        btn.textContent = prevText;
      }
    }

    async _syncPack(pack, el, sid) {
      const btn = el.querySelector(`#pack-sync-${sid}`);
      const fb  = el.querySelector(`#pack-card-fb-${sid}`);
      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Syncing…';

      try {
        const resp = await fetch(`/api/fraimic/scene_packs/${pack.id}/sync`, {
          method: 'POST', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        await this._loadAlbums();
        this._renderLibrary();
        await this._loadScenePacks();
        this._renderScenePacks();

        // _renderScenePacks() just tore down the card this callback's `fb`
        // reference pointed at, same as _installPack -- use the page-level
        // banner instead.
        const pageFb = this.shadowRoot.getElementById('pack-fb');
        if (result.errors && result.errors.length) {
          pageFb.className = 'feedback err';
          pageFb.textContent = `"${pack.name}" sync added ${result.images_added} image(s), but `
            + `failed: ${result.errors.map(e => e.filename).join(', ')}. Try syncing again later.`;
        } else if (result.images_added > 0) {
          pageFb.className = 'feedback ok';
          pageFb.textContent = `"${pack.name}": added ${result.images_added} missing/new image(s) `
            + `to the album. The scene wasn't changed -- edit it manually if you want them in rotation.`;
        } else {
          pageFb.className = 'feedback ok';
          pageFb.textContent = `"${pack.name}" is already up to date.`;
        }
        pageFb.style.display = 'block';
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Sync failed: ${err.message}`;
        fb.style.display = 'block';
        btn.disabled = false;
        btn.textContent = prevText;
      }
    }

    async _uninstallPack(pack, el, sid) {
      if (!window.confirm(`Remove pack "${pack.name}"? This deletes the images and scene it added.`)) return;

      const btn = el.querySelector(`#pack-remove-${sid}`);
      const fb  = el.querySelector(`#pack-card-fb-${sid}`);
      btn.disabled = true;
      btn.textContent = '⏳ Removing…';

      try {
        const resp = await fetch(`/api/fraimic/scene_packs/${pack.id}`, {
          method: 'DELETE', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }

        await this._loadAlbums();
        this._renderLibrary();
        await this._loadScenes();
        this._renderScenes();
        await this._loadScenePacks();
        this._renderScenePacks();
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Remove failed: ${err.message}`;
        fb.style.display = 'block';
        btn.disabled = false;
        btn.textContent = '🗑 Remove';
      }
    }

    // -----------------------------------------------------------------------
    // Scene pack preview -- a read-only, album-style gallery over a pack's
    // images. No send-to-frame here; it's just for browsing before installing.
    // -----------------------------------------------------------------------

    _wirePackPreview() {
      const root = this.shadowRoot;
      root.getElementById('pack-preview-close').addEventListener('click', () => this._closePackPreview());
      root.getElementById('pack-preview-prev').addEventListener('click', () => this._packPreviewStep(-1));
      root.getElementById('pack-preview-next').addEventListener('click', () => this._packPreviewStep(1));

      // Bound at window, not shadowRoot -- keydown only bubbles to a
      // shadowRoot listener if focus is already inside the shadow tree,
      // which isn't guaranteed here (the pack cover that opened this modal
      // doesn't take focus). Window-level catches the keypress regardless
      // of where focus happens to be. Registered via _addGlobalListeners
      // so the element lifecycle can detach/re-attach it.
      this._onPackPreviewKeydown = (e) => {
        if (!this._packPreview) return;
        if (e.key === 'Escape') this._closePackPreview();
        else if (e.key === 'ArrowLeft') this._packPreviewStep(-1);
        else if (e.key === 'ArrowRight') this._packPreviewStep(1);
      };
    }

    _openPackPreview(pack, index) {
      const images = pack.images || [];
      if (!images.length) return;
      this._packPreview = { pack, index };
      this.shadowRoot.getElementById('pack-preview-overlay').style.display = 'flex';
      this._renderPackPreview();
    }

    _closePackPreview() {
      this.shadowRoot.getElementById('pack-preview-overlay').style.display = 'none';
      this._packPreview = null;
    }

    _packPreviewStep(delta) {
      if (!this._packPreview) return;
      const { pack, index } = this._packPreview;
      const total = pack.images.length;
      this._packPreview.index = (index + delta + total) % total;
      this._renderPackPreview();
    }

    _renderPackPreview() {
      if (!this._packPreview) return;
      const { pack, index } = this._packPreview;
      const image = pack.images[index];
      const root = this.shadowRoot;

      root.getElementById('pack-preview-title').textContent = pack.name;
      root.getElementById('pack-preview-counter').textContent = `${index + 1} / ${pack.images.length}`;
      root.getElementById('pack-preview-img').src = `${SCENE_PACK_RAW_BASE}/${image.path}`;
      root.getElementById('pack-preview-img').alt = image.title || pack.name;

      const captionParts = [image.title, image.source].filter(Boolean);
      root.getElementById('pack-preview-caption').textContent = captionParts.join(' · ');

      // Prev/next wrap around rather than disabling at the ends -- a pack's
      // image list is a loop to browse, not a bounded sequence.
      const nav = pack.images.length > 1;
      root.getElementById('pack-preview-prev').style.display = nav ? '' : 'none';
      root.getElementById('pack-preview-next').style.display = nav ? '' : 'none';
    }

    async _editorSendToCanvas() {
      const st = this._editorState;
      const select = this.shadowRoot.getElementById('editor-frame-select');
      const entityId = select && select.value;
      if (!entityId) {
        this._editorShowFb('err', 'No frame selected yet.');
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
        if (this._packerOverride) form.append('packer', this._packerOverride);
        const resp = await fetch('/api/fraimic/library/send', {
          method: 'POST', headers: this._authHeaders(), body: form,
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        const sentFrame = this._frames.find(f => f.entityId === entityId);
        if (sentFrame) {
          sentFrame.lastImageId = st.image.image_id;
          this._renderFrames();
        }
        this._editorShowFb('ok', result.packer ? `✓ Sent! (packer: ${result.packer})` : '✓ Sent!');
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
      // Also escapes quotes -- callers embed this inside attribute values
      // (e.g. value="${this._esc(name)}") for user-supplied album names.
      return (str || '')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    // -----------------------------------------------------------------------
    // Shared section-header helpers -- used to split Library/Frames/Scenes
    // grids into labeled groups (user vs. add-on content) without an extra
    // drill-in click. Both are full-width items inside a CSS grid (see
    // .section-header / .section-empty, which span all columns).
    // -----------------------------------------------------------------------

    _buildSectionHeader(label) {
      const el = document.createElement('div');
      el.className = 'section-header';
      el.textContent = label;
      return el;
    }

    _buildSectionEmpty(icon, title, body) {
      const el = document.createElement('div');
      el.className = 'section-empty';
      el.innerHTML = `
        <div class="section-empty-icon">${icon}</div>
        <div class="section-empty-title">${this._esc(title)}</div>
        <div class="section-empty-body">${this._esc(body)}</div>
      `;
      return el;
    }
  }

  customElements.define('fraimic-panel', FraimicPanel);

  console.info(
    '%c FRAIMIC-PANEL %c v' + PANEL_VERSION + ' ',
    'background:#3b82f6;color:#fff;padding:2px 6px;border-radius:3px 0 0 3px;font-weight:600',
    'background:#1e293b;color:#fff;padding:2px 6px;border-radius:0 3px 3px 0',
  );
})();
