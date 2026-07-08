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

  // Labels for known add-on category tags. The Add-ons tab derives which
  // Art Pack category tiles to show from the tags in the remote pack catalog.
  const PACK_CATEGORIES = {
    famous_artists: { label: 'Famous Artists' },
    nature: { label: 'Nature' },
    architecture: { label: 'Architecture' },
    seasons: { label: 'Seasons & Holidays' },
    history: { label: 'History' },
    speed: { label: 'Speed' },
    productivity: { label: 'Productivity' }
  };
  const PRODUCTIVITY_CATEGORY = 'productivity';
  const PACK_CATEGORY_ORDER = [
    'famous_artists',
    'nature',
    'architecture',
    'seasons',
    'history',
    'speed',
  ];

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
    .card.deep-link-highlight,
    .wall-tile.deep-link-highlight {
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

    /* ---- walls (the Scenes tab's layout + preview canvas) ---- */
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
    .tile-remove-btn {
      position: absolute;
      top: 4px;
      right: 4px;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: rgba(0, 0, 0, 0.6);
      color: #fff;
      border: none;
      font-size: 10px;
      font-weight: bold;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10;
      opacity: 0;
      transition: opacity 0.15s ease, background 0.15s ease;
      padding: 0;
      line-height: 1;
    }
    .wall-tile:hover .tile-remove-btn {
      opacity: 1;
    }
    .tile-remove-btn:hover {
      background: rgba(239, 68, 68, 0.9);
    }
    .wall-palette-thumb {
      width: 28px;
      height: 28px;
      border-radius: 4px;
      overflow: hidden;
      background: var(--secondary-background-color, #ccc);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      flex-shrink: 0;
    }
    .wall-palette-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
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
    .wall-picker-header h3 { margin: 0; font-size: 15px; color: var(--primary-text-color); flex: 1 1 auto; }
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
    .orientation-toggle {
      display: flex;
      gap: 4px;
      flex: 0 0 auto;
    }
    .orientation-icon-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      padding: 0;
      border: none;
      border-radius: 6px;
      background: var(--secondary-background-color, #f1f5f9);
      color: var(--secondary-text-color);
      cursor: pointer;
    }
    .orientation-icon-btn.active {
      background: var(--primary-color, #3b82f6);
      color: #fff;
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
    .addons-section-title {
      font-size: 18px;
      font-weight: 600;
      color: var(--primary-text-color);
      margin: 0 0 16px;
      border-bottom: 2px solid var(--primary-color, #03a9f4);
      padding-bottom: 8px;
      display: inline-block;
    }
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

    /* Embedded config/options flow modal */
    .flow-desc {
      font-size: 13px;
      color: var(--secondary-text-color);
      margin: 0 0 14px;
      white-space: pre-line;
    }
    .flow-field-error {
      color: var(--error-color, #db4437);
      font-size: 12px;
      margin-top: 4px;
    }
    .flow-loading {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 18px 4px;
      color: var(--secondary-text-color);
      font-size: 14px;
    }
    .flow-loading::before {
      content: '';
      width: 18px;
      height: 18px;
      border: 2px solid var(--divider-color, #444);
      border-top-color: var(--primary-color, #03a9f4);
      border-radius: 50%;
      animation: flow-spin .8s linear infinite;
      flex: 0 0 auto;
    }
    @keyframes flow-spin { to { transform: rotate(360deg); } }
    .discovery-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 14px;
      padding: 12px 16px;
      border-radius: var(--ha-card-border-radius, 12px);
      background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
      border: 1px solid color-mix(in srgb, var(--primary-color, #03a9f4) 35%, transparent);
      font-size: 14px;
    }
    .wall-drag-ghost.colliding {
      outline: 2px solid #ef4444;
      background: rgba(239, 68, 68, .25) !important;
    }
    .wall-tile.selected {
      outline: 3px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }
    .wall-tile-media {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      font-size: 11px;
      text-align: center;
      padding: 2px;
      box-sizing: border-box;
    }
    .wall-tile-media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .wall-tile-footer {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      display: flex;
      align-items: center;
      gap: 3px;
      padding: 2px 4px;
      font-size: 10px;
      line-height: 1.3;
      background: rgba(15, 23, 42, .68);
      color: #fff;
      z-index: 2;
      pointer-events: none;
    }
    .wall-tile-footer .wall-tile-name {
      flex: 1 1 auto;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .wall-tile-footer .wall-tile-status { flex: 0 0 auto; white-space: nowrap; }
    .wall-tile-footer .wall-tile-gear {
      background: none;
      border: none;
      color: #fff;
      cursor: pointer;
      padding: 0 2px;
      font-size: 12px;
      flex: 0 0 auto;
      pointer-events: auto;
    }
    /* Send-model state: staged this session / mapped by the selected
       scene / merely showing the frame's current content. */
    .wall-tile-badge {
      position: absolute;
      top: 2px;
      left: 2px;
      z-index: 2;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: .4px;
      text-transform: uppercase;
      padding: 1px 6px;
      border-radius: 8px;
      color: #fff;
      pointer-events: none;
    }
    .wall-tile-badge[data-kind="staged"]  { background: var(--primary-color, #03a9f4); }
    .wall-tile-badge[data-kind="scene"]   { background: #8b5cf6; }
    .wall-tile-badge[data-kind="onframe"] { background: rgba(100, 116, 139, .9); }
    .discovery-banner .banner-add-btn {
      padding: 6px 14px;
      border-radius: 8px;
      border: none;
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
      font-weight: 600;
      cursor: pointer;
      flex: 0 0 auto;
    }
    .modal-row input[type="checkbox"] {
      width: auto;
      transform: scale(1.2);
      margin-right: auto;
    }
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

      this._scenePacks    = [];       // [{ id, name, description, categories, license, cover, images, installed, scene_created }]
      this._activeTab     = 'dashboard'; // 'dashboard' | 'addons'
      this._packCategory  = null;     // null = category-tile view; otherwise the category id being browsed
      this._packPreview   = null;     // { pack, index } while the read-only image gallery is open, else null

      // The Scenes tab *is* the Walls workflow -- a wall is just a saved
      // layout (frame positions) that the same canvas previews a scene
      // (frame->image mappings) against. See _renderWallsSubview.
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
      this._wallPickerSelectedFile = null; // raw photo staged for the picker's Send button, or null
      this._wallSelectedEntryId = null;    // tile selected for arrow-key nudging, or null
      this._wallSaveTimer = null;          // pending debounced layout auto-save, or null
      this._onWallPointerMove = this._onWallPointerMove.bind(this);
      this._onWallPointerUp   = this._onWallPointerUp.bind(this);
      this._onWallKeydown     = this._onWallKeydown.bind(this);

      // Embedded config/options flow state (the panel drives HA's own
      // data_entry_flow REST API instead of navigating to Settings).
      this._flowModal = null;         // { base, flowId, userInitiated, onDone, step } while open, else null
      this._flowTranslations = null;  // merged config+options translation resources, fetched once

      // First-run onboarding: { step: 1|2 } while the wizard is open, else
      // null. Opens automatically when the panel loads with zero frames.
      this._onboarding = null;
      this._frameSettingsTarget = null;  // frame whose settings menu is open, else null
      this._discoveredFlows = {};     // flow_id → in-progress discovery flow (banner data)
      this._flowSubUnsub = null;      // unsubscribe fn for config_entries/flow/subscribe, else null

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
      if (this._flowSubUnsub) {
        // The flow subscription lives on the shared hass websocket, not
        // this element -- left connected it would fire renders against a
        // detached shadow tree forever.
        try { this._flowSubUnsub(); } catch (err) { /* connection already gone */ }
        this._flowSubUnsub = null;
      }
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
      this._subscribeDiscoveredFlows();
      if (!this._loaded) return;
      // Grid <img>s still point at revoked blob: URLs -- re-render from
      // in-memory state so tiles re-register with the observer and refetch
      // (cheap: server-side disk thumbnail cache + browser HTTP cache).
      this._renderDashboard();
      this._renderLibrary();
      this._renderScenePacks();
    }

    // The three long-lived window/document listeners the panel needs.
    // Handler fields are created by _wireUploadModal/_wirePackPreview (run
    // once in _init); registration is separate so _revive can re-attach
    // them under the replacement AbortController.
    _addGlobalListeners() {
      const signal = this._abort.signal;
      // Arrow-key nudging for the selected wall tile. Capture phase on
      // purpose: it runs on the way DOWN from window to the target, so no
      // component between us and the focused element (HA's sidebar list
      // consumes arrow keys for its own navigation) can stopPropagation
      // it away from us. Guards in _onWallKeydown keep it polite.
      window.addEventListener('keydown', this._onWallKeydown, { signal, capture: true });
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
      this._wireFlowModal();
      this._wireFrameSettingsMenu();
      this._wireSettingsModal();
      this._wireOnboarding();
      this._wireWallToolbar();
      this._wireWallImagePicker();
      this._wirePackTest();
      this._addGlobalListeners();
      this._subscribeDiscoveredFlows();
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
      await Promise.all([backendP, albumsP]);
      this._renderLibrary();
      await Promise.all([scenesP, wallsP]);
      // Land on the default "All Frames" wall (backend-guaranteed to exist
      // and to hold a placement for every configured frame).
      if (!this._activeWallId && this._walls.length) {
        const initial = this._defaultWall() || this._walls[0];
        this._activeWallId = initial.wall_id;
        this._wallPlacements = JSON.parse(JSON.stringify(initial.placements || {}));
      }
      this._renderDashboard();
      // Deep links target wall tiles, so this must wait for the walls
      // render above.
      this._handleDeepLink();
      // Zero frames configured? Offer the first-run wizard (admins) or a
      // pointer to one (everyone else), on top of the rendered dashboard.
      this._maybeOpenOnboarding();
      await packsP;
      this._renderScenePacks();

      // Needs frames + albums, both awaited above.
      if (packTestRequested) this._openPackTestModal();
    }

    // Coming from a device page's "Visit" link (/fraimic?entry=<entry_id>):
    // select and scroll to that frame's tile on the dashboard wall.
    _handleDeepLink() {
      let entryId;
      try {
        entryId = new URLSearchParams(window.location.search).get('entry');
      } catch (err) {
        return;
      }
      if (!entryId) return;

      const canvas = this.shadowRoot.getElementById('wall-canvas');
      const tile = canvas && this._wallTileEl(canvas, entryId);
      if (!tile) return;

      this._setTab('dashboard');
      this._wallSelectTile(entryId);
      tile.scrollIntoView({ behavior: 'smooth', block: 'center' });
      tile.classList.add('deep-link-highlight');
      setTimeout(() => tile.classList.remove('deep-link-highlight'), 3000);
    }

    // -----------------------------------------------------------------------
    // Tab bar: Dashboard / Add-ons
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
        addBtn.addEventListener('click', () => this._openAddFrameFlow());
        // Admin-gated: the config-entry APIs behind the embedded flow are
        // @require_admin server-side.
        if (!this._isAdmin()) addBtn.style.display = 'none';
      }
      const libraryBtn = this.shadowRoot.getElementById('library-open-btn');
      if (libraryBtn) libraryBtn.addEventListener('click', () => this._openLibraryModal());
      this._setTab('dashboard');
    }

    _setTab(name) {
      this._activeTab = name;
      const root = this.shadowRoot;
      ['dashboard', 'addons'].forEach(tab => {
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
          <button class="tab-btn active" data-tab="dashboard">Dashboard</button>
          <button class="tab-btn" data-tab="addons">Add-ons</button>
        </div>

        <div class="tab-content active" id="tab-dashboard">
        <div class="discovery-banner" id="discovery-banner" style="display:none"></div>
        <div class="lib-toolbar">
          <div class="lib-backend">
            <label for="wall-select">Wall:</label>
            <select id="wall-select"><option value="">Untitled (unsaved)</option></select>
          </div>
          <div class="lib-toolbar-actions">
            <button class="btn-ghost" id="wall-new-btn" style="flex:0 0 auto">＋ New Wall</button>
            <button class="btn-ghost" id="wall-delete-btn" style="flex:0 0 auto;display:none">🗑 Delete Wall</button>
            <button class="btn-primary" id="frame-add-btn" style="flex:0 0 auto">＋ Add Frame</button>
            <button class="btn-ghost" id="library-open-btn" style="flex:0 0 auto">🖼 Manage Library</button>
            <button class="btn-ghost" id="settings-open-btn" style="flex:0 0 auto" title="Photo storage settings">⚙</button>
          </div>
        </div>
        <div class="feedback" id="wall-fb"></div>

        <div id="wall-editor">
          <h3 style="margin:16px 0 6px;font-size:14px">Layout</h3>
          <p style="font-size:12px;color:var(--secondary-text-color);margin:0 0 10px">
            Drag a frame from the palette onto the wall, then drag a placed frame to
            reposition it — positions snap to a grid, save automatically, and tiles
            can't overlap. Click a tile to select it, then nudge it with the arrow
            keys. A frame works the same whether it's on the wall or still in the
            palette — click it either way to choose its image.
          </p>
          <div class="wall-layout-row">
            <div class="wall-palette" id="wall-palette"></div>
            <div class="wall-canvas" id="wall-canvas"></div>
          </div>

          <h3 style="margin:22px 0 6px;font-size:14px">Select a Scene</h3>
          <div class="modal-row" style="max-width:320px">
            <label for="wall-scene-select">Scene</label>
            <select id="wall-scene-select"><option value="">Create New…</option></select>
          </div>
          <div class="wall-lock-hint" id="wall-lock-hint" style="display:none"></div>

          <div class="btns" style="margin-top:10px">
            <button class="btn-primary" id="wall-send-btn">▶ Send to Frames</button>
            <button class="btn-primary" id="wall-save-scene-btn">Save Scene</button>
            <button class="btn-ghost" id="wall-clear-all-btn" title="Clear every frame's image assignment (the physical frames are untouched until you send)">✕ Clear All</button>
            <button class="btn-ghost" id="wall-delete-scene-btn" style="display:none">🗑 Delete Scene</button>
          </div>
          <div class="feedback" id="wall-scene-fb"></div>
        </div>
        </div><!-- /tab-dashboard -->

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

        <!-- First-run onboarding: opens automatically when zero frames are
             configured. A thin shell over the proven pieces -- step 1
             launches the embedded Add-Frame flow (which stacks above at the
             standard modal z-index), step 2 offers storage setup via the
             Settings modal, then it lands on the dashboard. -->
        <div class="modal-overlay" id="onboarding-overlay" style="z-index:1000">
          <div class="modal-box" style="max-width:560px">
            <h3 id="onboarding-title">Welcome to Fraimic 👋</h3>
            <div id="onboarding-body"></div>
            <div class="modal-actions">
              <button class="btn-ghost" id="onboarding-skip">Set up later</button>
            </div>
          </div>
        </div>

        <!-- Manage Library: everything from the old Library tab except the
             backend picker (now in Settings) and per-frame sends (now
             inline on tile click) -- albums, upload, crop, tagging, bulk
             delete, Dropbox Discover. Markup relocated verbatim; all
             handlers find their elements by id and keep working. Sits at a
             lower z-index than its sub-modals (upload/album/crop) so they
             stack above it. -->
        <div class="modal-overlay" id="library-modal-overlay" style="z-index:900">
          <div class="modal-box" style="max-width:1100px;max-height:90vh;overflow-y:auto">
            <div class="lib-toolbar">
              <h3 style="margin:0;flex:1 1 auto">🖼 Library</h3>
              <div class="lib-toolbar-actions">
                <button class="btn-primary" id="lib-upload-btn" style="flex:0 0 auto">⬆ Upload to Library</button>
                <button class="btn-ghost" id="album-create-btn" style="flex:0 0 auto">＋ Create Album</button>
                <button class="btn-ghost" id="lib-discover-btn" style="display:none;flex:0 0 auto"
                  title="Adopt photos dropped into the Fraimic Library/inbox folder in Dropbox">🔍 Discover</button>
                <button class="btn-ghost" id="library-modal-close" style="flex:0 0 auto">✕ Close</button>
              </div>
            </div>
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
          </div>
        </div>

        <!-- Settings: the library storage-backend picker (Local / Google
             Drive / Dropbox), relocated from the old Library tab. The
             #backend-config contents are rendered by _renderBackendConfig,
             exactly as before -- only the markup's home moved. -->
        <div class="modal-overlay" id="settings-modal-overlay">
          <div class="modal-box">
            <h3>⚙ Settings</h3>
            <div class="modal-row">
              <label for="backend-select">Photo storage</label>
              <select id="backend-select">
                <option value="local">Local (this Home Assistant)</option>
                <option value="google_drive">Google Drive</option>
                <option value="dropbox">Dropbox</option>
              </select>
            </div>
            <div class="backend-config" id="backend-config"></div>
            <div class="feedback" id="settings-fb"></div>
            <div class="modal-actions">
              <button class="btn-ghost" id="settings-modal-close">Close</button>
            </div>
          </div>
        </div>

        <!-- Embedded config/options flow: a generic renderer for HA's
             data_entry_flow steps (add frame, reconfigure), so device
             management never has to leave the panel. Body content is
             rebuilt per step by _renderFlowStep. -->
        <div class="modal-overlay" id="flow-modal-overlay">
          <div class="modal-box">
            <h3 id="flow-modal-title">Add Frame</h3>
            <div id="flow-modal-body"></div>
            <div class="feedback" id="flow-modal-fb"></div>
            <div class="modal-actions">
              <button class="btn-primary" id="flow-modal-submit">Next</button>
              <button class="btn-ghost" id="flow-modal-cancel">Cancel</button>
            </div>
          </div>
        </div>

        <!-- Per-frame management: rename / reconfigure / remove without
             leaving the panel. Rename writes entry.title directly via the
             config_entries/update WS command (never the options flow's
             broken name field); Configure drives FraimicOptionsFlow through
             the flow modal above. -->
        <div class="modal-overlay" id="frame-settings-overlay">
          <div class="modal-box" style="max-width:440px">
            <h3 id="frame-settings-title">Frame Settings</h3>
            <div class="modal-row">
              <label>Name</label>
              <input type="text" id="frame-settings-name">
            </div>
            <div class="feedback" id="frame-settings-fb"></div>
            <div class="modal-actions" style="flex-wrap:wrap">
              <button class="btn-primary" id="frame-settings-rename">Save Name</button>
              <button class="btn-ghost" id="frame-settings-configure">⚙ Configure…</button>
              <button class="btn-ghost" id="frame-settings-reload" title="Reload this frame's integration">🔄 Reload</button>
              <button class="btn-ghost" id="frame-settings-remove">🗑 Remove</button>
              <button class="btn-ghost" id="frame-settings-close">Close</button>
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
              <div class="orientation-toggle" id="wall-image-picker-orientation">
                <button class="orientation-icon-btn" id="wall-image-picker-portrait" title="Portrait">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>
                </button>
                <button class="orientation-icon-btn" id="wall-image-picker-landscape" title="Landscape">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>
                </button>
              </div>
              <button class="btn-ghost" id="wall-image-picker-cancel" style="flex:0 0 auto;padding:4px 10px">✕</button>
            </div>
            <div class="wall-picker-body">
              <div class="modal-row">
                <label for="wall-image-picker-album">Album</label>
                <select id="wall-image-picker-album"></select>
              </div>
              <div class="wall-lock-hint" id="wall-image-picker-lock-hint" style="display:none"></div>
              <!-- Nothing transmits to the physical frame until the Send
                   button: clicking a thumbnail (or choosing a file) only
                   selects/stages. Sending is always its own deliberate
                   click. -->
              <div class="modal-row" style="flex-direction:row;gap:8px;flex-wrap:wrap">
                <button class="btn-primary" id="wall-picker-send-btn" style="flex:1 1 100%" disabled>▶ Send</button>
                <!-- Single-MIME accept on purpose: companion-app WebView
                     file choosers are unreliable with multi-MIME lists. -->
                <button class="btn-ghost" id="wall-picker-upload-btn" style="flex:1 1 auto">⬆ Upload a photo…</button>
                <input type="file" id="wall-picker-upload-input" accept="image/*" style="display:none">
                <button class="btn-ghost" id="wall-image-picker-clear" style="flex:1 1 auto">✕ Remove Image</button>
              </div>
              <div class="image-picker-grid" id="wall-image-picker-grid"></div>
              <div class="feedback" id="wall-image-picker-fb"></div>
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

    // Kept as a thin alias: many call sites (send-success refreshes, reload
    // timers, _revive, _refreshAfterEntryChange) historically refreshed the
    // Frames tab through this name -- they all now refresh the consolidated
    // dashboard.
    _renderFrames() {
      this._renderDashboard();
    }

    _renderDashboard() {
      this._renderDiscoveryBanner();
      this._renderWallsSubview();
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
      // Attribute-hook based (not id) so one code path serves every place a
      // frame's status appears -- today that's the wall tile footers.
      const els = this.shadowRoot.querySelectorAll(`[data-status-entity="${frame.entityId}"]`);
      if (!els.length) return;

      const state = this._hass.states[frame.entityId];
      let html;
      if (!state || state.state === 'unavailable' || state.state === 'unknown') {
        html = '<span class="dot-off">●</span>';
      } else {
        const pct = parseFloat(state.state);
        const bat = isNaN(pct) ? '' : `${pct >= 20 ? '🔋' : '🪫'}${pct}% `;
        html = `${bat}<span class="dot-on">●</span>`;
      }
      // hass is re-assigned on every state change of ANY entity in the
      // house -- skip the DOM write when this frame's status text is
      // unchanged, or the constant innerHTML churn janks whatever screen
      // is open.
      for (const el of els) {
        if (el._fraimicLastStatus === html) continue;
        el._fraimicLastStatus = html;
        el.innerHTML = html;
      }
    }

    // -----------------------------------------------------------------------
    // Embedded config/options flows: a generic renderer for HA's
    // data_entry_flow REST API, so adding/reconfiguring a frame never leaves
    // the panel. Drives both the config flow (add) and the options flow
    // (reconfigure) -- their wire formats are identical.
    // -----------------------------------------------------------------------

    _isAdmin() {
      // Every config-entry endpoint below is @require_admin server-side;
      // hide the affordances client-side so non-admins never see dead
      // buttons. No capability regression: those actions previously lived
      // behind HA Settings, which non-admins can't reach either.
      return !!(this._hass && this._hass.user && this._hass.user.is_admin);
    }

    async _loadFlowTranslations() {
      // The flow API returns raw field names/step ids; human strings live
      // in the frontend translation store. Fetched once, merged across the
      // config + options categories. Failure is non-fatal -- the renderer
      // falls back to raw names.
      if (this._flowTranslations) return this._flowTranslations;
      const resources = {};
      for (const category of ['config', 'options']) {
        try {
          const resp = await this._hass.callWS({
            type: 'frontend/get_translations',
            language: (this._hass.language || 'en'),
            category,
            integration: 'fraimic',
          });
          Object.assign(resources, (resp && resp.resources) || {});
        } catch (err) {
          console.warn(`[fraimic-panel] flow translations (${category}) unavailable:`, err);
        }
      }
      this._flowTranslations = resources;
      return resources;
    }

    _flowText(key, fallback, placeholders) {
      let text = (this._flowTranslations || {})[key];
      if (!text) return fallback;
      for (const [name, value] of Object.entries(placeholders || {})) {
        text = text.split(`{${name}}`).join(value);
      }
      return text;
    }

    async _flowRequest(method, url, body) {
      const resp = await fetch(url, {
        method,
        headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.message || detail.error || `HTTP ${resp.status}`);
      }
      // DELETE returns 200 with no meaningful body.
      return resp.json().catch(() => ({}));
    }

    _startConfigFlow() {
      return this._flowRequest('POST', '/api/config/config_entries/flow', {
        handler: 'fraimic',
        show_advanced_options: false,
      });
    }

    _startOptionsFlow(entryId) {
      return this._flowRequest('POST', '/api/config/config_entries/options/flow', {
        handler: entryId,
        show_advanced_options: false,
      });
    }

    _flowGet(base, flowId)            { return this._flowRequest('GET',    `${base}/${flowId}`); }
    _flowSubmit(base, flowId, values) { return this._flowRequest('POST',   `${base}/${flowId}`, values); }
    _flowDelete(base, flowId)         { return this._flowRequest('DELETE', `${base}/${flowId}`); }

    _wireFlowModal() {
      const overlay = this.shadowRoot.getElementById('flow-modal-overlay');
      const submit  = this.shadowRoot.getElementById('flow-modal-submit');
      const cancel  = this.shadowRoot.getElementById('flow-modal-cancel');
      submit.addEventListener('click', () => this._submitFlowStep());
      cancel.addEventListener('click', () => this._closeFlowModal());
      overlay.addEventListener('click', (e) => {
        // Backdrop click closes like Cancel; clicks inside the box don't.
        if (e.target === overlay) this._closeFlowModal();
      });
    }

    // start: a promise for the flow's first step (from _startConfigFlow /
    // _startOptionsFlow / _flowGet on a discovered flow_id).
    // userInitiated: user-started flows are DELETEd on cancel; discovered
    // flows must stay pending so their banner/Discovered card survives.
    async _openFlowModal({ title, base, start, userInitiated, onDone, loadingText }) {
      const overlay = this.shadowRoot.getElementById('flow-modal-overlay');
      const body    = this.shadowRoot.getElementById('flow-modal-body');
      const fb      = this.shadowRoot.getElementById('flow-modal-fb');
      this.shadowRoot.getElementById('flow-modal-title').textContent = title;
      fb.style.display = 'none';
      body.innerHTML = `<div class="flow-loading">${this._esc(loadingText || 'Loading…')}</div>`;
      this._setFlowButtons({ submit: false, cancel: true });
      overlay.style.display = 'flex';

      this._flowModal = { base, flowId: null, userInitiated: !!userInitiated, onDone, step: null };

      const translationsP = this._loadFlowTranslations();
      let result;
      try {
        result = await start();
      } catch (err) {
        if (!this._flowModal) return;   // closed while loading
        body.innerHTML = '';
        this._showFlowError(`Couldn't start: ${err.message}`);
        return;
      }
      await translationsP;
      if (!this._flowModal) return;     // closed while loading
      this._renderFlowStep(result);
    }

    _closeFlowModal() {
      const modal = this._flowModal;
      this._flowModal = null;
      this.shadowRoot.getElementById('flow-modal-overlay').style.display = 'none';
      if (modal && modal.userInitiated && modal.flowId && !modal.finished) {
        // Abandon the half-completed flow server-side, or it lingers in
        // flow/progress forever. Never done for discovered flows.
        this._flowDelete(modal.base, modal.flowId).catch(() => {});
      }
      // Without a live flow subscription (older HA), this is the moment
      // discovered-flow state most plausibly changed -- refresh the banner.
      if (modal && !this._flowSubUnsub) this._refreshDiscoveredFlowsOnce();
    }

    _setFlowButtons({ submit, cancel, submitLabel, cancelLabel }) {
      const submitBtn = this.shadowRoot.getElementById('flow-modal-submit');
      const cancelBtn = this.shadowRoot.getElementById('flow-modal-cancel');
      submitBtn.style.display = submit ? '' : 'none';
      cancelBtn.style.display = cancel ? '' : 'none';
      submitBtn.disabled = false;
      cancelBtn.disabled = false;
      submitBtn.textContent = submitLabel || 'Next';
      cancelBtn.textContent = cancelLabel || 'Cancel';
    }

    _showFlowError(message) {
      const fb = this.shadowRoot.getElementById('flow-modal-fb');
      fb.className = 'feedback err';
      fb.textContent = message;
      fb.style.display = 'block';
    }

    _renderFlowStep(result) {
      const modal = this._flowModal;
      if (!modal) return;
      modal.flowId = result.flow_id || modal.flowId;
      modal.step = result;
      const body = this.shadowRoot.getElementById('flow-modal-body');
      const fb   = this.shadowRoot.getElementById('flow-modal-fb');
      fb.style.display = 'none';
      body.innerHTML = '';

      const category = modal.base.includes('/options/') ? 'options' : 'config';
      const keyBase  = `component.fraimic.${category}`;

      if (result.type === 'create_entry') {
        modal.finished = true;
        this._closeFlowModal();
        if (modal.onDone) modal.onDone(result);
        return;
      }

      if (result.type === 'abort') {
        modal.finished = true;   // nothing left to cancel server-side
        const reason = this._flowText(
          `${keyBase}.abort.${result.reason}`,
          result.reason,
          result.description_placeholders,
        );
        body.innerHTML = `<p class="flow-desc">${this._esc(reason)}</p>`;
        this._setFlowButtons({ submit: false, cancel: true, cancelLabel: 'Close' });
        return;
      }

      if (result.type !== 'form') {
        // Our flows only emit form/create_entry/abort; menu/progress would
        // mean a future backend change this renderer predates.
        body.innerHTML = `<p class="flow-desc">Unsupported step type "${this._esc(result.type)}" — use HA Settings for this one.</p>`;
        this._setFlowButtons({ submit: false, cancel: true, cancelLabel: 'Close' });
        return;
      }

      const stepKey = `${keyBase}.step.${result.step_id}`;
      const title = this._flowText(`${stepKey}.title`, null, result.description_placeholders);
      if (title) this.shadowRoot.getElementById('flow-modal-title').textContent = title;
      const desc = this._flowText(`${stepKey}.description`, '', result.description_placeholders);
      if (desc) {
        const p = document.createElement('p');
        p.className = 'flow-desc';
        p.textContent = desc;
        body.appendChild(p);
      }

      const errors = result.errors || {};
      for (const field of (result.data_schema || [])) {
        body.appendChild(this._buildFlowField(field, stepKey, errors[field.name]));
      }
      if (errors.base) {
        this._showFlowError(this._flowText(`${keyBase}.error.${errors.base}`, errors.base));
      }

      const isLast = result.last_step !== false;   // null/true → likely final
      this._setFlowButtons({ submit: true, cancel: true, submitLabel: isLast ? 'Submit' : 'Next' });
      const firstInput = body.querySelector('input[type="text"], input[type="number"]');
      if (firstInput) firstInput.focus();
    }

    _buildFlowField(field, stepKey, errorCode) {
      const row = document.createElement('div');
      row.className = 'modal-row';

      const label = document.createElement('label');
      label.textContent = this._flowText(`${stepKey}.data.${field.name}`, field.name);
      row.appendChild(label);

      let input;
      if (field.type === 'select') {
        input = document.createElement('select');
        for (const opt of (field.options || [])) {
          // voluptuous_serialize emits [value, label] pairs.
          const [value, text] = Array.isArray(opt) ? opt : [opt, opt];
          const el = document.createElement('option');
          el.value = value;
          el.textContent = text;
          input.appendChild(el);
        }
        if (field.default !== undefined) input.value = field.default;
      } else if (field.type === 'boolean') {
        input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = !!field.default;
      } else if (field.type === 'integer') {
        input = document.createElement('input');
        input.type = 'number';
        if (field.valueMin !== undefined) input.min = field.valueMin;
        if (field.valueMax !== undefined) input.max = field.valueMax;
        if (field.default !== undefined) input.value = field.default;
      } else {
        // 'string' plus any future type we don't know -- a text box is the
        // safest degradation.
        input = document.createElement('input');
        input.type = 'text';
        if (field.default !== undefined) input.value = field.default;
      }
      input.id = `flow-field-${field.name}`;
      input.dataset.flowField = field.name;
      input.dataset.flowType = field.type || 'string';
      input.dataset.flowOptional = field.optional ? '1' : '';
      // Enter anywhere in the form submits the step -- typing a name and
      // hitting Enter must behave like clicking the submit button.
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this._submitFlowStep();
        }
      });
      row.appendChild(input);

      const hint = this._flowText(`${stepKey}.data_description.${field.name}`, '');
      if (hint) {
        const p = document.createElement('div');
        p.className = 'modal-file-summary';
        p.textContent = hint;
        row.appendChild(p);
      }
      if (errorCode) {
        const category = stepKey.includes('.options.') ? 'options' : 'config';
        const err = document.createElement('div');
        err.className = 'flow-field-error';
        err.textContent = this._flowText(`component.fraimic.${category}.error.${errorCode}`, errorCode);
        row.appendChild(err);
      }
      return row;
    }

    _collectFlowValues() {
      const body = this.shadowRoot.getElementById('flow-modal-body');
      const values = {};
      for (const input of body.querySelectorAll('[data-flow-field]')) {
        const name = input.dataset.flowField;
        switch (input.dataset.flowType) {
          case 'boolean':
            values[name] = input.checked;
            break;
          case 'integer': {
            const n = parseInt(input.value, 10);
            if (!isNaN(n)) values[name] = n;
            break;
          }
          default:
            // Empty optional strings are sent as "" on purpose: an empty
            // host is the "scan my network instead" signal in
            // async_step_user.
            values[name] = input.value;
        }
      }
      return values;
    }

    async _submitFlowStep() {
      const modal = this._flowModal;
      if (!modal || !modal.step || modal.step.type !== 'form') return;
      const submitBtn = this.shadowRoot.getElementById('flow-modal-submit');
      const values = this._collectFlowValues();
      submitBtn.disabled = true;
      submitBtn.textContent = 'Working…';
      try {
        const result = await this._flowSubmit(modal.base, modal.flowId, values);
        if (this._flowModal !== modal) return;   // closed mid-flight
        this._renderFlowStep(result);
      } catch (err) {
        if (this._flowModal !== modal) return;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Next';
        this._showFlowError(err.message);
      }
    }

    // -----------------------------------------------------------------------
    // Frame management: embedded add / rename / reconfigure / remove
    // -----------------------------------------------------------------------

    _openAddFrameFlow() {
      this._openFlowModal({
        title: 'Add Frame',
        base: '/api/config/config_entries/flow',
        start: () => this._startConfigFlow(),
        userInitiated: true,
        // async_step_user auto-scans the subnet before its first form.
        loadingText: 'Scanning your network for frames…',
        onDone: () => {
          this._onboardingFrameAdded();
          this._refreshAfterEntryChange();
        },
      });
    }

    async _refreshAfterEntryChange() {
      // HA sets the new entry up asynchronously after create_entry -- give
      // it a beat before re-reading, same pattern as the reload button.
      await new Promise((r) => setTimeout(r, 2000));
      if (this._disposed) return;
      await this._discoverFrames();
      this._renderFrames();
      await this._loadWalls();
      this._renderWallsSubview();
    }

    _wireFrameSettingsMenu() {
      const overlay = this.shadowRoot.getElementById('frame-settings-overlay');
      const fb      = this.shadowRoot.getElementById('frame-settings-fb');

      const close = () => {
        this._frameSettingsTarget = null;
        overlay.style.display = 'none';
      };
      this.shadowRoot.getElementById('frame-settings-close')
        .addEventListener('click', close);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

      this.shadowRoot.getElementById('frame-settings-rename')
        .addEventListener('click', async (e) => {
          const frame = this._frameSettingsTarget;
          if (!frame) return;
          const name = this.shadowRoot.getElementById('frame-settings-name').value.trim();
          if (!name || name === frame.title) { close(); return; }
          e.target.disabled = true;
          try {
            // Two registries to update: the config entry's title (panel
            // cards, Settings → Integrations) AND the device registry's
            // user-facing name (device page, entity names) -- entry title
            // alone leaves the device showing its creation-time name.
            await this._hass.callWS({
              type: 'config_entries/update',
              entry_id: frame.entryId,
              title: name,
            });
            if (frame.deviceId) {
              await this._hass.callWS({
                type: 'config/device_registry/update',
                device_id: frame.deviceId,
                name_by_user: name,
              });
            }
            close();
            await this._refreshAfterEntryChange();
          } catch (err) {
            fb.className = 'feedback err';
            fb.textContent = `Rename failed: ${err.message || err.code || err}`;
            fb.style.display = 'block';
          } finally {
            e.target.disabled = false;
          }
        });

      this.shadowRoot.getElementById('frame-settings-configure')
        .addEventListener('click', () => {
          const frame = this._frameSettingsTarget;
          if (!frame) return;
          close();
          this._openFlowModal({
            title: `Configure ${frame.title}`,
            base: '/api/config/config_entries/options/flow',
            start: () => this._startOptionsFlow(frame.entryId),
            userInitiated: true,
            onDone: () => this._refreshAfterEntryChange(),
          });
        });

      this.shadowRoot.getElementById('frame-settings-reload')
        .addEventListener('click', async (e) => {
          const frame = this._frameSettingsTarget;
          if (!frame) return;
          e.target.disabled = true;
          try {
            const resp = await fetch('/api/fraimic/frame/reload', {
              method: 'POST',
              headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
              body: JSON.stringify({ entry_id: frame.entryId }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            close();
            await this._refreshAfterEntryChange();
          } catch (err) {
            fb.className = 'feedback err';
            fb.textContent = `Reload failed: ${err.message}`;
            fb.style.display = 'block';
          } finally {
            e.target.disabled = false;
          }
        });

      this.shadowRoot.getElementById('frame-settings-remove')
        .addEventListener('click', async (e) => {
          const frame = this._frameSettingsTarget;
          if (!frame) return;
          if (!window.confirm(`Remove "${frame.title}" from Home Assistant? Its images and scenes stay in the library.`)) return;
          e.target.disabled = true;
          try {
            await this._flowRequest(
              'DELETE', `/api/config/config_entries/entry/${frame.entryId}`
            );
            close();
            await this._refreshAfterEntryChange();
          } catch (err) {
            fb.className = 'feedback err';
            fb.textContent = `Remove failed: ${err.message}`;
            fb.style.display = 'block';
          } finally {
            e.target.disabled = false;
          }
        });
    }

    _openLibraryModal() {
      this.shadowRoot.getElementById('library-modal-overlay').style.display = 'flex';
      // The grid's lazy-thumbnail observers never fired while the modal was
      // display:none -- nudge a render now that tiles can intersect.
      this._renderLibrary();
    }

    _closeLibraryModal() {
      this.shadowRoot.getElementById('library-modal-overlay').style.display = 'none';
    }

    _wireSettingsModal() {
      const overlay = this.shadowRoot.getElementById('settings-modal-overlay');
      const close = () => { overlay.style.display = 'none'; };
      this.shadowRoot.getElementById('settings-modal-close').addEventListener('click', close);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      this.shadowRoot.getElementById('backend-select')
        .addEventListener('change', (e) => this._renderBackendConfig(e.target.value));
      const openBtn = this.shadowRoot.getElementById('settings-open-btn');
      if (openBtn) openBtn.addEventListener('click', () => this._openSettingsModal());
    }

    _openSettingsModal() {
      const sel = this.shadowRoot.getElementById('backend-select');
      sel.value = this._backend;
      this._renderBackendConfig(this._backend);
      this.shadowRoot.getElementById('settings-fb').style.display = 'none';
      this.shadowRoot.getElementById('settings-modal-overlay').style.display = 'flex';
    }

    _openFrameSettingsMenu(frame) {
      this._frameSettingsTarget = frame;
      this.shadowRoot.getElementById('frame-settings-title').textContent = frame.title;
      this.shadowRoot.getElementById('frame-settings-name').value = frame.title;
      const fb = this.shadowRoot.getElementById('frame-settings-fb');
      fb.style.display = 'none';
      this.shadowRoot.getElementById('frame-settings-overlay').style.display = 'flex';
    }

    // -----------------------------------------------------------------------
    // Discovered-frames banner: frames found by the backend's periodic scan
    // (or DHCP) surface here too, not just on HA's Settings page. Clicking
    // Add resumes that exact pending flow -- straight to the naming step.
    // -----------------------------------------------------------------------

    _isDiscoveryFlow(flow) {
      const source = flow && flow.context && flow.context.source;
      return flow && flow.handler === 'fraimic'
        && !['user', 'import', 'reconfigure'].includes(source);
    }

    _requestDiscoveryScan() {
      // Frames sleep, so the backend's boot-time sweep goes stale --
      // opening the panel re-runs it, and results land on the banner via
      // the flow subscription. Fire-and-forget: a failed rescan just means
      // the banner shows the last sweep's state.
      if (!this._isAdmin()) return;
      fetch('/api/fraimic/discovery/scan', {
        method: 'POST',
        headers: this._authHeaders(),
      }).catch(() => {});
    }

    async _subscribeDiscoveredFlows() {
      if (!this._isAdmin()) return;   // flow/progress APIs are admin-only
      this._requestDiscoveryScan();
      try {
        this._flowSubUnsub = await this._hass.connection.subscribeMessage(
          (events) => {
            for (const ev of (Array.isArray(events) ? events : [events])) {
              if (ev.type === 'removed') {
                delete this._discoveredFlows[ev.flow_id];
              } else if (ev.flow && this._isDiscoveryFlow(ev.flow)) {
                this._discoveredFlows[ev.flow.flow_id] = ev.flow;
              }
            }
            this._renderDiscoveryBanner();
          },
          { type: 'config_entries/flow/subscribe' },
        );
      } catch (err) {
        // Older HA cores don't have flow/subscribe -- fall back to a
        // one-shot snapshot, refreshed whenever a flow modal closes (see
        // _closeFlowModal).
        await this._refreshDiscoveredFlowsOnce();
      }
    }

    async _refreshDiscoveredFlowsOnce() {
      if (!this._isAdmin()) return;
      try {
        const flows = await this._hass.callWS({ type: 'config_entries/flow/progress' });
        this._discoveredFlows = {};
        for (const flow of (flows || [])) {
          if (this._isDiscoveryFlow(flow)) this._discoveredFlows[flow.flow_id] = flow;
        }
        this._renderDiscoveryBanner();
      } catch (err) {
        console.warn('[fraimic-panel] discovered-flow refresh failed:', err);
      }
    }

    _renderDiscoveryBanner() {
      const banner = this.shadowRoot.getElementById('discovery-banner');
      if (!banner) return;
      const flows = Object.values(this._discoveredFlows);
      if (!flows.length || !this._isAdmin()) {
        banner.style.display = 'none';
        banner.innerHTML = '';
        if (this._onboarding && this._onboarding.step === 1) this._renderOnboardingStep();
        return;
      }
      banner.innerHTML = '';
      const label = document.createElement('span');
      label.textContent = flows.length === 1
        ? '📡 1 frame found on your network:'
        : `📡 ${flows.length} frames found on your network:`;
      banner.appendChild(label);
      for (const flow of flows) {
        const name = (flow.context && flow.context.title_placeholders
          && flow.context.title_placeholders.name) || 'frame';
        const btn = document.createElement('button');
        btn.className = 'banner-add-btn';
        btn.textContent = `＋ Add ${name}`;
        btn.addEventListener('click', () => this._openDiscoveredFlow(flow));
        banner.appendChild(btn);
      }
      banner.style.display = 'flex';
      // The wizard's step 1 mirrors this list -- keep it in sync as
      // subscribe events arrive.
      if (this._onboarding && this._onboarding.step === 1) this._renderOnboardingStep();
    }

    _openDiscoveredFlow(flow) {
      this._openFlowModal({
        title: 'Add Frame',
        base: '/api/config/config_entries/flow',
        // GET on a pending flow re-serves its current step (the naming
        // form) without restarting anything.
        start: () => this._flowGet('/api/config/config_entries/flow', flow.flow_id),
        userInitiated: false,   // cancel must NOT delete a discovered flow
        onDone: () => {
          delete this._discoveredFlows[flow.flow_id];
          this._renderDiscoveryBanner();
          this._onboardingFrameAdded();
          this._refreshAfterEntryChange();
        },
      });
    }

    // -----------------------------------------------------------------------
    // First-run onboarding: auto-opens when the panel loads with zero
    // frames. A shell over the proven pieces -- the embedded Add-Frame flow
    // and the Settings modal do the real work, stacking above the wizard.
    // -----------------------------------------------------------------------

    _wireOnboarding() {
      this.shadowRoot.getElementById('onboarding-skip')
        .addEventListener('click', () => this._dismissOnboarding());
      // Deliberately no backdrop-click dismiss: this overlay IS the page's
      // content at zero frames; "Set up later" is the explicit exit.
    }

    _maybeOpenOnboarding() {
      if (this._frames.length) {
        // Frames exist (again) -- a previous dismissal shouldn't suppress
        // the wizard if the user ever ends up back at zero.
        try { localStorage.removeItem('fraimic_onboarding_dismissed'); } catch (err) { /* private mode */ }
        return;
      }
      if (!this._isAdmin()) {
        const fb = this.shadowRoot.getElementById('wall-fb');
        fb.className = 'feedback';
        fb.textContent = 'No frames configured yet — ask your Home Assistant administrator to add one.';
        fb.style.display = 'block';
        return;
      }
      let dismissed = false;
      try { dismissed = localStorage.getItem('fraimic_onboarding_dismissed') === '1'; } catch (err) { /* private mode */ }
      if (dismissed) return;
      this._onboarding = { step: 1 };
      this._renderOnboardingStep();
      this.shadowRoot.getElementById('onboarding-overlay').style.display = 'flex';
    }

    _renderOnboardingStep() {
      const wizard = this._onboarding;
      if (!wizard) return;
      const body  = this.shadowRoot.getElementById('onboarding-body');
      const title = this.shadowRoot.getElementById('onboarding-title');
      const skip  = this.shadowRoot.getElementById('onboarding-skip');

      if (wizard.step === 1) {
        title.textContent = 'Welcome to Fraimic 👋';
        body.innerHTML = `
          <p class="flow-desc">Let's put a picture on your wall. First, add a frame — make sure it's awake (tap it) and on the same network as Home Assistant.</p>
          <div class="modal-row">
            <button class="btn-primary" id="onboarding-add-btn">＋ Add your first frame</button>
          </div>
          <div id="onboarding-discovered"></div>
        `;
        body.querySelector('#onboarding-add-btn')
          .addEventListener('click', () => this._openAddFrameFlow());

        // Frames the background scan already found get one-click adds,
        // exactly like the dashboard's discovery banner.
        const discovered = Object.values(this._discoveredFlows || {});
        const list = body.querySelector('#onboarding-discovered');
        if (discovered.length) {
          const p = document.createElement('p');
          p.className = 'flow-desc';
          p.textContent = 'Already spotted on your network:';
          list.appendChild(p);
          for (const flow of discovered) {
            const name = (flow.context && flow.context.title_placeholders
              && flow.context.title_placeholders.name) || 'frame';
            const btn = document.createElement('button');
            btn.className = 'banner-add-btn';
            btn.style.margin = '0 6px 6px 0';
            btn.textContent = `＋ Add ${name}`;
            btn.addEventListener('click', () => this._openDiscoveredFlow(flow));
            list.appendChild(btn);
          }
        }
        skip.style.display = '';
        return;
      }

      title.textContent = 'Frame added 🎉';
      body.innerHTML = `
        <p class="flow-desc">Your frame is on the dashboard — click its tile any time to choose what it shows. One last thing: where should your photo library live? Local storage on this Home Assistant is already set up and works great; Google Drive and Dropbox are options too.</p>
        <div class="modal-actions" style="justify-content:flex-start">
          <button class="btn-primary" id="onboarding-finish">Continue with current storage</button>
          <button class="btn-ghost" id="onboarding-storage-btn">⚙ Choose photo storage…</button>
        </div>
      `;
      body.querySelector('#onboarding-finish')
        .addEventListener('click', () => this._finishOnboarding());
      body.querySelector('#onboarding-storage-btn')
        .addEventListener('click', () => this._openSettingsModal());
      skip.style.display = 'none';
    }

    // Called from every add-frame completion path (manual flow, discovered
    // flow) -- advances the wizard past step 1 if it's what started the add.
    _onboardingFrameAdded() {
      if (this._onboarding && this._onboarding.step === 1) {
        this._onboarding.step = 2;
        this._renderOnboardingStep();
      }
    }

    _finishOnboarding() {
      this._onboarding = null;
      this.shadowRoot.getElementById('onboarding-overlay').style.display = 'none';
    }

    _dismissOnboarding() {
      try { localStorage.setItem('fraimic_onboarding_dismissed', '1'); } catch (err) { /* private mode */ }
      this._finishOnboarding();
    }

    // -----------------------------------------------------------------------
    // Library: toolbar wiring
    // -----------------------------------------------------------------------

    _wireLibraryToolbar() {
      const uploadBtn       = this.shadowRoot.getElementById('lib-upload-btn');
      const backBtn         = this.shadowRoot.getElementById('lib-back-btn');
      const albumCreateBtn  = this.shadowRoot.getElementById('album-create-btn');
      const discoverBtn     = this.shadowRoot.getElementById('lib-discover-btn');
      const selectToggleBtn = this.shadowRoot.getElementById('lib-select-toggle');
      const selectCancelBtn = this.shadowRoot.getElementById('lib-select-cancel');
      const selectDeleteBtn = this.shadowRoot.getElementById('lib-select-delete');

      uploadBtn.addEventListener('click', () => this._openUploadModal());
      backBtn.addEventListener('click', () => this._openAlbumFolders());
      const libraryOverlay = this.shadowRoot.getElementById('library-modal-overlay');
      this.shadowRoot.getElementById('library-modal-close')
        .addEventListener('click', () => this._closeLibraryModal());
      libraryOverlay.addEventListener('click', (e) => {
        if (e.target === libraryOverlay) this._closeLibraryModal();
      });
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

    // container is overridable so the first-run wizard can mount the same
    // backend picker inline instead of in the Settings modal.
    _renderBackendConfig(selected, container = this.shadowRoot.getElementById('backend-config')) {
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
      const fb = this.shadowRoot.getElementById('settings-fb');
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
      const fb = this.shadowRoot.getElementById('settings-fb');
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
        } else if (result.queued) {
          fb.className = 'feedback ok';
          fb.textContent = '⏳ Frame is asleep — image queued, will send when it wakes.';
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
    // Scenes are only ever created/edited/deleted through the wall canvas
    // below (see _saveWallScene/_deleteWallScene) -- there's no separate
    // scene list or editor.
    // -----------------------------------------------------------------------

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

    // -----------------------------------------------------------------------
    // Walls -- a virtual layout of a subset of the user's frames, positioned
    // the way they're physically hung. Pure panel-local state: a wall only
    // stores where each frame sits on a free-form canvas, never which image
    // it shows. Loading a scene onto a wall and saving back is done entirely
    // against the existing scenes API -- see _saveWallScene. This canvas is
    // the entire content of the Scenes tab -- there's no wall selection
    // gate: the first wall (or an empty draft, if none exists yet) is always
    // showing, and a frame behaves identically whether it's placed on the
    // canvas or still sitting in the palette -- click it either way to
    // assign/change its image; dragging only ever changes its position.
    // -----------------------------------------------------------------------

    _wireWallToolbar() {
      // No unsaved-changes guard: layout edits auto-save (debounced), so
      // switching walls never discards anything -- a pending save fires
      // with its own snapshot of the wall it belongs to.
      this.shadowRoot.getElementById('wall-select').addEventListener('change', (e) => {
        this._openWall(e.target.value || null);
      });
      this.shadowRoot.getElementById('wall-new-btn').addEventListener('click', () => this._createWall());
      this.shadowRoot.getElementById('wall-delete-btn').addEventListener('click', () => this._deleteWall());
      this.shadowRoot.getElementById('wall-scene-select').addEventListener('change', (e) => {
        this._loadSceneOntoWall(e.target.value || null);
      });
      this.shadowRoot.getElementById('wall-save-scene-btn').addEventListener('click', () => this._saveWallScene());
      this.shadowRoot.getElementById('wall-clear-all-btn').addEventListener('click', () => this._clearAllWallAssignments());
      this.shadowRoot.getElementById('wall-delete-scene-btn').addEventListener('click', () => this._deleteWallScene());
      this.shadowRoot.getElementById('wall-send-btn').addEventListener('click', () => this._sendWallToFrames());
    }

    // Empty the send model in one click: every frame gets an explicit ''
    // pending entry (the same "cleared" sentinel the per-tile ✕ uses), which
    // overrides the selected scene's mappings in _wallEffectiveMapping. The
    // physical frames are untouched until something is actually sent.
    _clearAllWallAssignments() {
      for (const frame of this._frames) {
        this._wallPendingMappings[frame.entryId] = '';
      }
      this._renderWallCanvas();
      const fb = this.shadowRoot.getElementById('wall-scene-fb');
      fb.className = 'feedback ok';
      fb.textContent = '✕ Cleared all assignments — the frames themselves are untouched.';
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 4000);
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

    _activeWall() {
      return this._walls.find(w => w.wall_id === this._activeWallId) || null;
    }

    _defaultWall() {
      return this._walls.find(w => w.kind === 'default') || null;
    }

    _renderWallsSubview() {
      const select = this.shadowRoot.getElementById('wall-select');
      // Default wall always listed first; custom walls in creation order.
      const walls = [...this._walls].sort((a, b) => {
        if (a.kind === 'default') return -1;
        if (b.kind === 'default') return 1;
        return (a.created_at || 0) - (b.created_at || 0);
      });
      select.innerHTML = walls.length
        ? walls.map(w => `<option value="${this._esc(w.wall_id)}">${this._esc(w.name)}</option>`).join('')
        : '<option value="">Untitled (unsaved)</option>';
      select.value = this._activeWallId || '';

      // The default wall is permanent -- no delete affordance.
      const active = this._activeWall();
      this.shadowRoot.getElementById('wall-delete-btn').style.display =
        (active && active.kind !== 'default') ? '' : 'none';

      this._renderWallScenePicker();
      this._renderWallCanvas();
    }

    _openWall(wallId) {
      // With the backend-guaranteed default wall there's no "no wall"
      // state anymore -- fall back to it instead of an unsaveable draft.
      let wall = wallId && this._walls.find(w => w.wall_id === wallId);
      if (!wall) wall = this._defaultWall() || this._walls[0] || null;
      this._activeWallId = wall ? wall.wall_id : null;
      // Deep-copy so in-progress canvas edits never mutate this._walls
      // directly -- the local record only updates when a save round-trips.
      this._wallPlacements = wall ? JSON.parse(JSON.stringify(wall.placements || {})) : {};
      this._wallActiveSceneId = null;
      this._wallPendingMappings = {};
      this._wallPendingPickAlbum = {};
      this._wallSelectedEntryId = null;
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
      // Land on the default wall -- it always exists.
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

    // Would placing entryId's tile at (x, y) overlap any other placed tile?
    // Strict AABB overlap -- tiles sharing an edge at a grid boundary are
    // legal, so a tight gallery layout is still possible.
    _wallCollidesAt(entryId, x, y) {
      const frame = this._frames.find(f => f.entryId === entryId);
      const dims = this._wallTileDims(frame);
      for (const [otherId, pos] of Object.entries(this._wallPlacements)) {
        if (otherId === entryId) continue;
        const otherFrame = this._frames.find(f => f.entryId === otherId);
        if (!otherFrame) continue;
        const otherDims = this._wallTileDims(otherFrame);
        if (
          x < pos.x + otherDims.width && pos.x < x + dims.width
          && y < pos.y + otherDims.height && pos.y < y + dims.height
        ) {
          return true;
        }
      }
      return false;
    }

    // The canvas position a drag would snap to if dropped at the pointer's
    // current location -- one shared implementation for the actual drop
    // (_onWallPointerUp) and the ghost's live collision hint.
    _wallSnapCandidate(drag, clientX, clientY) {
      const canvas = this.shadowRoot.getElementById('wall-canvas');
      const canvasRect = canvas.getBoundingClientRect();
      const rawX = drag.kind === 'palette'
        ? (clientX - canvasRect.left + canvas.scrollLeft - drag.dims.width / 2)
        : (drag.startLeft + (clientX - drag.startClientX));
      const rawY = drag.kind === 'palette'
        ? (clientY - canvasRect.top + canvas.scrollTop - drag.dims.height / 2)
        : (drag.startTop + (clientY - drag.startClientY));
      const GRID = 20;
      return {
        x: Math.max(0, Math.round(rawX / GRID) * GRID),
        y: Math.max(0, Math.round(rawY / GRID) * GRID),
      };
    }

    _wallSelectTile(entryId) {
      this._wallSelectedEntryId = entryId || null;
      const canvas = this.shadowRoot.getElementById('wall-canvas');
      if (!canvas) return;
      for (const tile of canvas.querySelectorAll('.wall-tile')) {
        const isSelected = tile.dataset.entryId === this._wallSelectedEntryId;
        tile.classList.toggle('selected', isSelected);
        if (isSelected) {
          // Pull keyboard focus onto the tile. Without this, focus stays
          // wherever it was -- in real HA that's usually the sidebar's
          // list item (our pointerdown preventDefault blocks the normal
          // click-focus transfer), and the sidebar's own arrow-key
          // navigation eats the nudge keys before they reach us.
          tile.focus({ preventScroll: true });
        }
      }
    }

    _onWallKeydown(e) {
      if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape'].includes(e.key)) return;
      if (this._activeTab !== 'dashboard') return;
      // Never steal keys from form fields.
      const target = e.composedPath ? e.composedPath()[0] : e.target;
      const tag = target && target.tagName;
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) return;

      if (e.key === 'Escape') {
        // Escape dismisses the topmost thing: the image picker first (it
        // has no key handling of its own -- without this, Escape after a
        // tile click cleared the selection while the picker stayed open,
        // and the arrow keys then read as completely dead), then the tile
        // selection.
        const picker = this.shadowRoot.getElementById('wall-image-picker-overlay');
        if (picker && picker.style.display === 'block') {
          this._closeWallImagePicker();
          return;
        }
        this._wallSelectTile(null);
        return;
      }

      const entryId = this._wallSelectedEntryId;
      if (!entryId || !(entryId in this._wallPlacements)) return;
      for (const overlay of this.shadowRoot.querySelectorAll('.modal-overlay, .editor-overlay')) {
        if (overlay.style.display && overlay.style.display !== 'none') return;
      }

      e.preventDefault();
      const GRID = 20;
      const pos = this._wallPlacements[entryId];
      let x = pos.x, y = pos.y;
      if (e.key === 'ArrowLeft')  x = Math.max(0, x - GRID);
      if (e.key === 'ArrowRight') x = x + GRID;
      if (e.key === 'ArrowUp')    y = Math.max(0, y - GRID);
      if (e.key === 'ArrowDown')  y = y + GRID;
      if (x === pos.x && y === pos.y) return;
      // A nudge into a neighbor is a no-op, never a shove.
      if (this._wallCollidesAt(entryId, x, y)) return;

      this._wallPlacements[entryId] = { x, y };
      const canvas = this.shadowRoot.getElementById('wall-canvas');
      const tileEl = this._wallTileEl(canvas, entryId);
      if (tileEl) {
        tileEl.style.left = `${x}px`;
        tileEl.style.top  = `${y}px`;
      }
      this._scheduleWallLayoutSave();
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

          const imageId = this._wallEffectiveMapping(frame.entryId);
          if (imageId) {
            item.style.display = 'flex';
            item.style.alignItems = 'center';
            item.style.gap = '8px';
            item.style.cursor = 'grab';
            item.innerHTML = `
              <div class="wall-palette-thumb">🖼</div>
              <div style="flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${this._esc(frame.title)}</div>
            `;
            this._loadThumbnail(imageId, item.querySelector('.wall-palette-thumb'));
          } else {
            item.textContent = frame.title;
          }

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
        // Focusable so _wallSelectTile can move keyboard focus here (out
        // of HA's sidebar) -- and for plain keyboard/tab accessibility.
        tile.tabIndex = 0;
        if (entryId === this._wallSelectedEntryId) tile.classList.add('selected');
        canvas.appendChild(tile);

        this._renderWallTileContent(tile, entryId, frame);

        // Footer: the frame's name, live status, and (for admins) the
        // manage gear -- the consolidated dashboard's per-frame surface.
        const footer = document.createElement('div');
        footer.className = 'wall-tile-footer';
        const nameEl = document.createElement('span');
        nameEl.className = 'wall-tile-name';
        nameEl.textContent = frame.title;
        footer.appendChild(nameEl);
        const statusEl = document.createElement('span');
        statusEl.className = 'wall-tile-status';
        statusEl.dataset.statusEntity = frame.entityId;
        footer.appendChild(statusEl);
        if (this._isAdmin()) {
          const gear = document.createElement('button');
          gear.className = 'wall-tile-gear';
          gear.textContent = '⚙';
          gear.title = 'Frame settings';
          gear.addEventListener('pointerdown', (e) => e.stopPropagation());
          gear.addEventListener('click', (e) => {
            e.stopPropagation();
            this._openFrameSettingsMenu(frame);
          });
          footer.appendChild(gear);
        }
        tile.appendChild(footer);

        // Every frame is permanently placed on the default wall (the
        // backend re-adds it anyway) -- only custom walls get the ✕.
        const activeWall = this._activeWall();
        if (!activeWall || activeWall.kind !== 'default') {
          const removeBtn = document.createElement('button');
          removeBtn.className = 'tile-remove-btn';
          removeBtn.innerHTML = '✕';
          removeBtn.title = 'Remove frame from wall';
          removeBtn.addEventListener('pointerdown', (e) => e.stopPropagation());
          removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            delete this._wallPlacements[entryId];
            if (this._wallSelectedEntryId === entryId) this._wallSelectedEntryId = null;
            this._renderWallCanvas();
            this._scheduleWallLayoutSave();
          });
          tile.appendChild(removeBtn);
        }

        tile.addEventListener('pointerdown', (e) => this._wallBeginDrag(e, entryId, 'tile'));
      }

      this._updateWallSaveToSceneAvailability();
      if (this._hass) this._tickAllStatus();
    }

    // Sends whatever's currently previewed for every known frame (pending
    // edits take priority over the loaded scene's own mapping, per
    // _wallEffectiveMapping) straight to the physical frames -- same
    // per-image endpoint the Library tab's "Send to frame" button uses, so
    // this works whether or not the preview has been saved back to a scene
    // yet. Not scoped to placed tiles -- a frame not on this wall's canvas
    // still gets sent if it has an image assigned, since placement and
    // "active" are unrelated (see the note above this section).
    // One library image → one physical frame, immediately. Shared by the
    // per-tile picker (send-on-pick) and "Send to Frames" (whole wall).
    // Returns { queued } on acceptance; throws on a real failure.
    async _sendLibraryImageToFrame(frame, imageId) {
      const form = new FormData();
      form.append('entity_id', frame.entityId);
      form.append('image_id', imageId);
      if (this._packerOverride) form.append('packer', this._packerOverride);
      const resp = await fetch('/api/fraimic/library/send', {
        method: 'POST', headers: this._authHeaders(), body: form,
      });
      const result = await resp.json().catch(() => ({}));
      if (result.queued) return { queued: true };
      if (!resp.ok || !result.success) {
        throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
      }
      return { queued: false };
    }

    async _sendWallToFrames() {
      const fb  = this.shadowRoot.getElementById('wall-scene-fb');
      const btn = this.shadowRoot.getElementById('wall-send-btn');

      const targets = this._frames
        .map(frame => ({
          entryId: frame.entryId,
          frame,
          imageId: this._wallEffectiveMapping(frame.entryId),
        }))
        .filter(t => t.frame && t.frame.entityId && t.imageId);

      if (!targets.length) {
        fb.className = 'feedback err';
        fb.textContent = 'No frames have an image assigned yet.';
        fb.style.display = 'block';
        return;
      }

      const prevText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '⏳ Sending…';

      const results = await Promise.all(targets.map(async (t) => {
        try {
          const r = await this._sendLibraryImageToFrame(t.frame, t.imageId);
          if (r.queued) return { ...t, success: false, queued: true };
          return { ...t, success: true };
        } catch (err) {
          return { ...t, success: false, message: err.message };
        }
      }));

      const ok     = results.filter(r => r.success);
      // Queued frames haven't actually received the image yet -- don't
      // optimistically update lastImageId for those, only for immediate
      // successes.
      const queued = results.filter(r => r.queued);
      const failed = results.filter(r => !r.success && !r.queued);

      if (ok.length) {
        for (const r of ok) r.frame.lastImageId = r.imageId;
        this._renderFrames();
      }

      const parts = [];
      if (ok.length) parts.push(`✓ Sent to ${ok.length} frame${ok.length === 1 ? '' : 's'}`);
      if (queued.length) {
        parts.push(`⏳ ${queued.length} asleep — queued: `
          + queued.map(q => q.frame.title).join(', '));
      }
      if (failed.length) {
        parts.push(`✗ failed: ` + failed.map(f => `${f.frame.title}: ${f.message}`).join(', '));
      }
      fb.className = failed.length ? 'feedback err' : 'feedback ok';
      fb.textContent = parts.join('  ');
      fb.style.display = 'block';

      btn.disabled = false;
      btn.textContent = prevText;
    }

    // Keeps the Save Scene button (and the explanatory hint above it) in
    // sync with the album lock -- called after every wall canvas render.
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
        hint.textContent = `Save Scene is off -- this add-on scene is locked to the "${lockedAlbum}" album ` +
          `and at least one pick here comes from elsewhere. Switch the scene picker to "Create New…" to keep ` +
          `it as a new scene, or re-pick from "${lockedAlbum}" to re-enable saving back to the original.`;
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
      // Media lives in its own child so re-rendering an image never wipes
      // the tile's footer (name/status/gear) or remove button.
      let media = tile.querySelector('.wall-tile-media');
      if (!media) {
        media = document.createElement('div');
        media.className = 'wall-tile-media';
        tile.prepend(media);
      }
      // State badge: at a glance, is this tile part of the send model
      // (staged this session / mapped by the selected scene) or just
      // showing what's physically on the frame right now?
      let badge = tile.querySelector('.wall-tile-badge');
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'wall-tile-badge';
        tile.appendChild(badge);
      }

      const imageId = this._wallEffectiveMapping(entryId);
      if (imageId) {
        media.innerHTML = '';
        // _loadThumbnail paints synchronously on a cache hit and dedupes
        // concurrent fetches, so repeated renders and same-image tiles are
        // cheap.
        this._loadThumbnail(imageId, media);
        const stagedThisSession =
          Object.prototype.hasOwnProperty.call(this._wallPendingMappings, entryId)
          && this._wallPendingMappings[entryId];
        badge.textContent = stagedThisSession ? 'staged' : 'scene';
        badge.dataset.kind = stagedThisSession ? 'staged' : 'scene';
        badge.style.display = '';
        return;
      }

      // No assignment for this tile. Two modes (per Dale):
      // - VIEWING (no scene selected, nothing staged/cleared): show what's
      //   actually on the physical frame, labeled "on frame".
      // - MODELING (a scene is selected, or any pick/clear was made this
      //   session): a tile without an assignment must read BLANK -- blank
      //   means "Send to Frames will not touch this frame", and showing
      //   the frame's current content here would make the send model
      //   ambiguous again.
      const modeling = !!this._wallActiveSceneId
        || Object.keys(this._wallPendingMappings).length > 0;
      if (!modeling && frame.lastImageId) {
        media.innerHTML = '';
        this._loadThumbnail(frame.lastImageId, media);
        badge.textContent = 'on frame';
        badge.dataset.kind = 'onframe';
        badge.style.display = '';
      } else if (!modeling && frame.hasThumbnail) {
        media.innerHTML = `<img src="/api/fraimic/frame/${this._esc(frame.entryId)}/thumbnail" alt="">`;
        badge.textContent = 'on frame';
        badge.dataset.kind = 'onframe';
        badge.style.display = '';
      } else {
        media.innerHTML = `<div>${this._esc(frame.title)}</div>`;
        badge.style.display = 'none';
      }
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
      // Live hint: tint the ghost red when the drop it represents would be
      // rejected for overlapping another tile. Runs at most once per rAF.
      const { x, y } = this._wallSnapCandidate(drag, drag.lastX, drag.lastY);
      drag.ghost.classList.toggle('colliding', this._wallCollidesAt(drag.entryId, x, y));
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

      if (!drag.moved) {
        // A click, not a drag -- select the tile (for arrow-key nudging)
        // and open the image picker for this frame instead of
        // "repositioning"/"placing" it. Applies to a palette item exactly
        // the same as a placed tile: a frame works the same on or off the
        // wall, so clicking either one always means "choose its image,"
        // never "place it here."
        if (drag.kind === 'tile') this._wallSelectTile(drag.entryId);
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

      const { x, y } = this._wallSnapCandidate(drag, e.clientX, e.clientY);

      if (this._wallCollidesAt(drag.entryId, x, y)) {
        // Tiles never overlap: a colliding tile-drag snaps back to where
        // it started; a colliding palette-drop cancels.
        if (drag.kind === 'tile' && tileEl) {
          tileEl.style.left = `${drag.startLeft}px`;
          tileEl.style.top  = `${drag.startTop}px`;
        } else {
          this._renderWallCanvas();
        }
        return;
      }

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
      this._scheduleWallLayoutSave();
    }

    // Layout persistence is automatic: every drop/nudge/remove schedules a
    // debounced save of a snapshot taken at schedule time, so a save in
    // flight always belongs to the wall (and state) it was scheduled for --
    // switching walls mid-debounce can't cross-write.
    _scheduleWallLayoutSave() {
      const wall = this._activeWall();
      if (!wall) return;
      if (this._wallSaveTimer) clearTimeout(this._wallSaveTimer);
      const wallId = wall.wall_id;
      const name = wall.name;
      const snapshot = JSON.parse(JSON.stringify(this._wallPlacements));
      this._wallSaveTimer = setTimeout(() => {
        this._wallSaveTimer = null;
        this._persistWallLayout(wallId, name, snapshot);
      }, 800);
    }

    async _persistWallLayout(wallId, name, placements) {
      const fb = this.shadowRoot.getElementById('wall-fb');
      try {
        const resp = await fetch(`/api/fraimic/walls/${wallId}`, {
          method: 'POST',
          headers: { ...this._authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, placements }),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        // Sync the local record so a wall switch round-trip shows what was
        // just saved, without refetching the whole list.
        const wall = this._walls.find(w => w.wall_id === wallId);
        if (wall) wall.placements = result.wall.placements;
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't save layout: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    _renderWallScenePicker() {
      const select = this.shadowRoot.getElementById('wall-scene-select');
      select.innerHTML = '<option value="">Create New…</option>' +
        this._scenes.map(s => `<option value="${this._esc(s.scene_id)}">${this._esc(s.name)}</option>`).join('');
      select.value = this._wallActiveSceneId || '';
      this.shadowRoot.getElementById('wall-delete-scene-btn').style.display = this._wallActiveSceneId ? '' : 'none';
    }

    _loadSceneOntoWall(sceneId) {
      this._wallActiveSceneId = sceneId || null;
      this._wallPendingMappings = {};
      this._wallPendingPickAlbum = {};
      // Toggles the Delete Scene button too -- see _renderWallScenePicker.
      this._renderWallScenePicker();
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
    // this is what disables Save Scene for an existing add-on scene
    // (switching the picker to "Create New…" is never affected, since
    // forking into a new user-owned scene is always allowed). Clearing a
    // tile's image doesn't count -- only actually picking an off-album
    // image does.
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
      this.shadowRoot.getElementById('wall-image-picker-portrait').addEventListener('click', () => this._setWallImagePickerOrientation('portrait'));
      this.shadowRoot.getElementById('wall-image-picker-landscape').addEventListener('click', () => this._setWallImagePickerOrientation('landscape'));
      // Clicking the transparent backdrop (not the panel itself) closes the
      // picker -- e.target is only the overlay element when the click lands
      // outside .wall-picker-box, same as a normal modal's "click outside
      // to dismiss", just without a darkened background.
      this.shadowRoot.getElementById('wall-image-picker-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'wall-image-picker-overlay') this._closeWallImagePicker();
      });

      // "Upload a photo…" only STAGES the file (deliberately not a library
      // import; the Manage Library modal is for that) -- the Send button is
      // the one and only transmit action, same as library picks.
      const uploadBtn   = this.shadowRoot.getElementById('wall-picker-upload-btn');
      const uploadInput = this.shadowRoot.getElementById('wall-picker-upload-input');
      uploadBtn.addEventListener('click', () => uploadInput.click());
      uploadInput.addEventListener('change', () => {
        const file = uploadInput.files && uploadInput.files[0];
        uploadInput.value = '';   // same file can be re-picked next time
        if (!file) return;
        this._wallPickerSelectedFile = file;
        const grid = this.shadowRoot.getElementById('wall-image-picker-grid');
        grid.querySelectorAll('.image-picker-cell.selected').forEach(c => c.classList.remove('selected'));
        const fb = this.shadowRoot.getElementById('wall-image-picker-fb');
        fb.className = 'feedback ok';
        fb.textContent = `"${file.name}" ready — press Send below.`;
        fb.style.display = 'block';
        this._updateWallPickerSendButton();
      });

      this.shadowRoot.getElementById('wall-picker-send-btn')
        .addEventListener('click', () => this._sendFromWallPicker());

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
      this._wallPickerSelectedFile = null;
      this._updateWallPickerSendButton();

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

      this._updateWallImagePickerOrientationButtons();
      // Closed while the album load above was in flight? Showing the
      // overlay now would resurrect a picker the user already dismissed.
      if (this._wallImagePickerEntryId !== entryId) return;
      overlay.style.display = 'block';
      await this._loadWallImagePickerImages();
    }

    // Small portrait/landscape icon buttons in the picker header, right
    // where the user is already looking at this frame -- selecting a frame
    // to change its image is also the moment to change its orientation.
    // Same underlying select.select_option service call the Frames tab's
    // orientation dropdown uses; applies to the next image sent, not
    // whatever's already on the physical frame.
    _updateWallImagePickerOrientationButtons() {
      const entryId = this._wallImagePickerEntryId;
      const frame = entryId && this._frames.find(f => f.entryId === entryId);
      const portraitBtn  = this.shadowRoot.getElementById('wall-image-picker-portrait');
      const landscapeBtn = this.shadowRoot.getElementById('wall-image-picker-landscape');
      const has = !!(frame && frame.orientationEntityId);
      portraitBtn.style.display  = has ? '' : 'none';
      landscapeBtn.style.display = has ? '' : 'none';
      portraitBtn.classList.toggle('active', !!frame && frame.orientation === 'portrait');
      landscapeBtn.classList.toggle('active', !!frame && frame.orientation === 'landscape');
    }

    async _setWallImagePickerOrientation(orientation) {
      const entryId = this._wallImagePickerEntryId;
      const frame = entryId && this._frames.find(f => f.entryId === entryId);
      if (!frame || !frame.orientationEntityId) return;

      try {
        await this._hass.callService('select', 'select_option', {
          entity_id: frame.orientationEntityId,
          option: orientation === 'portrait' ? 'Portrait' : 'Landscape',
        });
        frame.orientation = orientation;
        this._updateWallImagePickerOrientationButtons();
        // The tile's on-canvas size is orientation-aware (see _wallTileDims).
        this._renderWallCanvas();
      } catch (err) {
        console.error('[fraimic-panel] failed to set orientation:', err);
        alert('Failed to change orientation.');
      }
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
        hint.textContent = `Picking outside "${lockedAlbum}" will disable Save Scene for this session -- ` +
          `switch the scene picker to "Create New…" to keep this pick as a new scene instead.`;
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

        if (image.image_id === this._wallEffectiveMapping(entryId)) {
          cell.classList.add('selected');
        }
        cell.addEventListener('click', () => {
          // Selecting only STAGES: highlight here, live preview on the
          // tile behind the transparent backdrop, and the pending-mapping
          // write that Save Scene has always merged from. Nothing reaches
          // the physical frame until the Send button below -- sending is
          // always its own deliberate click.
          grid.querySelectorAll('.image-picker-cell.selected').forEach(c => c.classList.remove('selected'));
          cell.classList.add('selected');
          this._wallPickerSelectedFile = null;
          this._wallPendingMappings[entryId] = image.image_id;
          // Recorded at the moment of picking, from whichever album filter
          // was active right now -- not the image's own album tags -- so
          // this stays a simple, predictable "did you leave the scene's
          // locked album to make this pick" check (see _wallHasOffAlbumPick).
          this._wallPendingPickAlbum[entryId] = album;
          this._renderWallCanvas();
          this._updateWallPickerSendButton();
        });
        grid.appendChild(cell);
      }
      this._updateWallPickerSendButton();
    }

    _updateWallPickerSendButton() {
      const btn = this.shadowRoot.getElementById('wall-picker-send-btn');
      const entryId = this._wallImagePickerEntryId;
      const frame = entryId && this._frames.find(f => f.entryId === entryId);
      if (!frame) {
        btn.disabled = true;
        btn.textContent = '▶ Send';
        return;
      }
      if (this._wallPickerSelectedFile) {
        btn.disabled = false;
        btn.textContent = `▶ Send "${this._wallPickerSelectedFile.name}" to ${frame.title}`;
        return;
      }
      const imageId = this._wallEffectiveMapping(entryId);
      btn.disabled = !imageId;
      btn.textContent = `▶ Send to ${frame.title}`;
    }

    // The picker's one transmit action: sends whatever is staged (a library
    // selection, or an uploaded file) to this frame, then closes.
    async _sendFromWallPicker() {
      const entryId = this._wallImagePickerEntryId;
      const frame = entryId && this._frames.find(f => f.entryId === entryId);
      if (!frame || !frame.entityId) return;
      const file = this._wallPickerSelectedFile;
      const imageId = this._wallEffectiveMapping(entryId);
      if (!file && !imageId) return;
      this._closeWallImagePicker();

      const fb = this.shadowRoot.getElementById('wall-scene-fb');
      fb.className = 'feedback ok';
      fb.textContent = `⏳ Sending to ${frame.title}…`;
      fb.style.display = 'block';
      try {
        let queued = false;
        if (file) {
          const form = new FormData();
          form.append('entity_id', frame.entityId);
          form.append('image', file);
          const resp = await fetch('/api/fraimic/send_image', {
            method: 'POST', headers: this._authHeaders(), body: form,
          });
          const result = await resp.json().catch(() => ({}));
          if (result.queued) queued = true;
          else if (!resp.ok || !result.success) {
            throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
          }
        } else {
          const r = await this._sendLibraryImageToFrame(frame, imageId);
          queued = r.queued;
          if (!queued) frame.lastImageId = imageId;
        }
        fb.textContent = queued
          ? `⏳ ${frame.title} is asleep — image queued for delivery on wake.`
          : `✓ Sent to ${frame.title}.`;
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Send to ${frame.title} failed: ${err.message}`;
      }
      setTimeout(() => { fb.style.display = 'none'; }, 4000);
    }

    _closeWallImagePicker() {
      this.shadowRoot.getElementById('wall-image-picker-overlay').style.display = 'none';
      this._wallImagePickerEntryId = null;
      this._wallPickerSelectedFile = null;
    }

    // "Create New…" (no active scene) prompts for a name and creates one;
    // an existing scene selected in the picker gets updated in place. Every
    // known frame's current effective mapping (see _wallEffectiveMapping)
    // is what gets saved -- not just frames placed on this wall's canvas,
    // since a frame works the same on or off it.
    async _saveWallScene() {
      const fb = this.shadowRoot.getElementById('wall-scene-fb');

      if (!this._wallActiveSceneId) {
        const name = window.prompt('Name for the new scene:');
        if (!name || !name.trim()) return;

        const mappings = {};
        for (const frame of this._frames) {
          const imageId = this._wallEffectiveMapping(frame.entryId);
          if (imageId) mappings[frame.entryId] = imageId;
        }
        if (!Object.keys(mappings).length) {
          fb.className = 'feedback err';
          fb.textContent = 'Assign an image to at least one frame first.';
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

          fb.className = 'feedback ok';
          fb.textContent = `Created scene "${result.scene.name}".`;
          fb.style.display = 'block';
          setTimeout(() => { fb.style.display = 'none'; }, 3000);
        } catch (err) {
          fb.className = 'feedback err';
          fb.textContent = `Couldn't create scene: ${err.message}`;
          fb.style.display = 'block';
        }
        return;
      }

      // The button is already disabled for this -- this is a backstop, not
      // the primary guard, in case this ever gets invoked some other way.
      if (this._wallHasOffAlbumPick()) {
        fb.className = 'feedback err';
        fb.textContent = `This add-on scene is locked to the "${this._wallSceneAlbumLock()}" album -- ` +
          'switch the scene picker to "Create New…" to keep a pick from outside it.';
        fb.style.display = 'block';
        return;
      }

      try {
        await this._loadScenes();
        const scene = this._scenes.find(s => s.scene_id === this._wallActiveSceneId);
        if (!scene) {
          // Don't just dead-end here -- whatever the user picked is still
          // intact in this._wallPendingMappings, so point them at
          // "Create New…" instead of discarding it.
          console.error(
            '[fraimic-panel] wall scene save: active scene not found after reload',
            { activeSceneId: this._wallActiveSceneId, availableSceneIds: this._scenes.map(s => s.scene_id) }
          );
          this._wallActiveSceneId = null;
          this._renderWallScenePicker();
          throw new Error(
            "that scene isn't available anymore (renamed or deleted elsewhere). " +
            'Your image choices are still applied here -- switch to "Create New…" to save them as a new scene.'
          );
        }

        // Every currently known frame's effective mapping replaces its
        // entry in the scene (deleted if empty) -- mappings for an entry_id
        // that isn't a known frame at all (e.g. a since-removed frame) are
        // left untouched, since this session has no opinion on them.
        const mergedMappings = { ...scene.mappings };
        for (const frame of this._frames) {
          const imageId = this._wallEffectiveMapping(frame.entryId);
          if (imageId) {
            mergedMappings[frame.entryId] = imageId;
          } else {
            delete mergedMappings[frame.entryId];
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

        fb.className = 'feedback ok';
        fb.textContent = `Saved scene "${scene.name}".`;
        fb.style.display = 'block';
        setTimeout(() => { fb.style.display = 'none'; }, 3000);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't save scene: ${err.message}`;
        fb.style.display = 'block';
      }
    }

    async _deleteWallScene() {
      const scene = this._scenes.find(s => s.scene_id === this._wallActiveSceneId);
      if (!scene) return;
      if (!window.confirm(`Delete scene "${scene.name}"? This can't be undone.`)) return;

      const fb = this.shadowRoot.getElementById('wall-scene-fb');
      try {
        const resp = await fetch(`/api/fraimic/scenes/${scene.scene_id}`, {
          method: 'DELETE', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        await this._loadScenes();
        this._wallActiveSceneId = null;
        this._wallPendingMappings = {};
        this._wallPendingPickAlbum = {};
        this._renderWallScenePicker();
        this._renderWallCanvas();
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Couldn't delete scene: ${err.message}`;
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
        grid.className = '';
        grid.innerHTML = `
          <div class="addons-section">
            <h2 class="addons-section-title">Art Packs</h2>
            <div class="category-grid" id="art-categories-grid"></div>
          </div>
          <div class="addons-section" style="margin-top: 40px;">
            <h2 class="addons-section-title">Productivity Packs</h2>
            <div class="lib-grid" id="productivity-grid"></div>
          </div>
        `;
        
        const artGrid = grid.querySelector('#art-categories-grid');
        const prodGrid = grid.querySelector('#productivity-grid');
        
        const artPacks = this._scenePacks.filter(p => !this._isProductivityPack(p));
        for (const catId of this._artPackCategoryIds(artPacks)) {
          const packs = artPacks.filter(p => this._packCategoryTags(p).includes(catId));
          if (packs.length > 0) {
            artGrid.appendChild(this._buildCategoryTile(catId, packs));
          }
        }
        
        const prodPacks = this._scenePacks.filter(p => this._isProductivityPack(p));
        for (const pack of prodPacks) {
          prodGrid.appendChild(this._buildPackCard(pack));
        }
        return;
      }

      const catInfo = this._packCategoryInfo(this._packCategory);
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
      for (const pack of this._scenePacks.filter(p => {
        return !this._isProductivityPack(p) && this._packCategoryTags(p).includes(this._packCategory);
      })) {
        grid.appendChild(this._buildPackCard(pack));
      }
    }

    _packCategoryTags(pack) {
      const raw = Array.isArray(pack.categories)
        ? pack.categories
        : (Array.isArray(pack.category) ? pack.category : [pack.category || 'famous_artists']);
      const tags = [];
      for (const tag of raw) {
        if (typeof tag !== 'string') continue;
        const normalized = tag.trim();
        if (normalized && !tags.includes(normalized)) tags.push(normalized);
      }
      return tags.length ? tags : ['famous_artists'];
    }

    _isProductivityPack(pack) {
      return pack.type === 'widget' || this._packCategoryTags(pack).includes(PRODUCTIVITY_CATEGORY);
    }

    _packCategoryInfo(catId) {
      if (PACK_CATEGORIES[catId]) return PACK_CATEGORIES[catId];
      return {
        label: String(catId || '')
          .replace(/[_-]+/g, ' ')
          .replace(/\b\w/g, c => c.toUpperCase()),
      };
    }

    _artPackCategoryIds(packs) {
      const ids = [];
      for (const pack of packs) {
        for (const tag of this._packCategoryTags(pack)) {
          if (tag === PRODUCTIVITY_CATEGORY || ids.includes(tag)) continue;
          ids.push(tag);
        }
      }
      return ids.sort((a, b) => {
        const ai = PACK_CATEGORY_ORDER.indexOf(a);
        const bi = PACK_CATEGORY_ORDER.indexOf(b);
        if (ai !== -1 && bi !== -1) return ai - bi;
        if (ai !== -1) return -1;
        if (bi !== -1) return 1;
        return 0;
      });
    }

    _buildCategoryTile(catId, packs) {
      const info = this._packCategoryInfo(catId);
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
            <button class="btn-primary" id="pack-run-${sid}">▶ Refresh</button>
            <button class="btn-ghost" id="pack-configure-${sid}">⚙ Settings</button>
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
          el.querySelector(`#pack-run-${sid}`)
            .addEventListener('click', () => this._runWidget(pack, el, sid));
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
      submitBtn.disabled = false;
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
      
      let basicFieldsHtml = '';
      let weatherFieldsHtml = '';
      
      for (const field of (pack.config_schema || [])) {
        const fieldId = `widget-field-${field.name}`;
        const label = field.label || field.name;
        const required = field.required ? 'required' : '';
        const placeholder = field.placeholder || '';
        
        if (field.name === 'quote_feed') {
          let fieldHtml = `
            <div class="modal-row">
              <label for="${fieldId}">${this._esc(label)}</label>
              <select id="${fieldId}">
                <option value="zenquotes">ZenQuotes (Inspirational)</option>
                <option value="favqs">FavQs (General)</option>
                <option value="custom">Custom API URL...</option>
              </select>
            </div>
          `;
          basicFieldsHtml += fieldHtml;
        } else if (field.name === 'bible_translation') {
          let fieldHtml = `
            <div class="modal-row">
              <label for="${fieldId}">${this._esc(label)}</label>
              <select id="${fieldId}">
                <option value="niv">NIV (New International Version)</option>
                <option value="kjv">KJV (King James Version)</option>
                <option value="web">WEB (World English Bible)</option>
                <option value="bbe">BBE (Bible in Basic English)</option>
                <option value="oeb">OEB (Open English Bible)</option>
                <option value="rvr1960">RVR1960 (Spanish Reina Valera)</option>
                <option value="almeida">Almeida (Portuguese João Ferreira)</option>
              </select>
            </div>
          `;
          basicFieldsHtml += fieldHtml;
        } else if (field.name === 'scripture_source') {
          let fieldHtml = `
            <div class="modal-row">
              <label for="${fieldId}">${this._esc(label)}</label>
              <select id="${fieldId}">
                <option value="daily_api">Daily Verse of the Day</option>
                <option value="custom_list">Custom list configured in JSON</option>
              </select>
            </div>
          `;
          basicFieldsHtml += fieldHtml;
        } else if (field.name === 'quote_api_url') {
          let fieldHtml = `
            <div class="modal-row" id="widget-quote-custom-row" style="display:none">
              <label for="${fieldId}">${this._esc(label)}</label>
              <input type="text" id="${fieldId}" placeholder="${this._esc(placeholder)}">
            </div>
          `;
          basicFieldsHtml += fieldHtml;
        } else {
          let fieldHtml = `
            <div class="modal-row">
              <label for="${fieldId}">${this._esc(label)}</label>
              <input type="text" id="${fieldId}" placeholder="${this._esc(placeholder)}" ${required}>
          `;
          
          if (field.name === 'calendar_url') {
            fieldHtml += `<div style="font-size:11px;color:var(--secondary-text-color);margin-top:4px;line-height:1.4">To get this: Open Google Calendar on desktop, go to <strong>Settings</strong> > click your calendar name in the left panel > scroll down to <strong>Integrate calendar</strong> > copy the <strong>Secret address in iCal format</strong>.</div>`;
          }
          
          fieldHtml += `</div>`;
          
          if (field.name === 'zip_code') {
            weatherFieldsHtml += fieldHtml;
          } else {
            basicFieldsHtml += fieldHtml;
          }
        }
      }
      
      html += basicFieldsHtml;
      
      if (weatherFieldsHtml) {
        html += `
          <details style="margin-top:16px;cursor:pointer">
            <summary style="font-weight:500;font-size:13.5px;color:var(--primary-color)">Location / Weather Settings (Optional)</summary>
            <div style="padding-top:8px">
              ${weatherFieldsHtml}
              <div style="font-size:11px;color:var(--secondary-text-color);margin-top:4px;line-height:1.4">
                Leave blank to automatically use your Home Assistant system coordinates.
              </div>
            </div>
          </details>
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
      
      const quoteFeedSel = this.shadowRoot.getElementById('widget-field-quote_feed');
      const quoteCustomRow = this.shadowRoot.getElementById('widget-quote-custom-row');
      if (quoteFeedSel && quoteCustomRow) {
        const updateQuoteRow = () => {
          quoteCustomRow.style.display = quoteFeedSel.value === 'custom' ? 'block' : 'none';
        };
        quoteFeedSel.addEventListener('change', updateQuoteRow);
        updateQuoteRow();
      }
      
      if (pack.installed && pack.config) {
        const config = pack.config;
        const frameSel = this.shadowRoot.getElementById('widget-config-frame');
        if (config.frame_id) frameSel.value = config.frame_id;
        
        for (const field of (pack.config_schema || [])) {
          const val = config[field.name];
          if (val !== undefined) {
            const el = this.shadowRoot.getElementById(`widget-field-${field.name}`);
            if (el) el.value = val;
          }
        }
        
        if (quoteFeedSel && quoteCustomRow) {
          quoteCustomRow.style.display = quoteFeedSel.value === 'custom' ? 'block' : 'none';
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
          const el = this.shadowRoot.getElementById(`widget-field-${field.name}`);
          if (!el) continue;
          const val = el.value.trim();
          
          if (field.name === 'quote_api_url') {
            const isCustomFeed = quoteFeedSel && quoteFeedSel.value === 'custom';
            if (isCustomFeed && !val) {
              fb.textContent = 'Custom API URL is required.';
              fb.className = 'feedback err';
              fb.style.display = 'block';
              return;
            }
          } else if (field.required && !val) {
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

    async _runWidget(pack, el, sid) {
      const btn = el.querySelector(`#pack-run-${sid}`);
      const fb  = el.querySelector(`#pack-card-fb-${sid}`);
      btn.disabled = true;
      const prevText = btn.textContent;
      btn.textContent = '⏳ Refreshing…';
      
      try {
        const resp = await fetch(`/api/fraimic/scene_packs/${pack.id}/sync`, {
          method: 'POST', headers: this._authHeaders(),
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        }
        fb.className = 'feedback ok';
        fb.textContent = 'Frame refreshed!';
        fb.style.display = 'block';
        setTimeout(() => { fb.style.display = 'none'; }, 3000);
      } catch (err) {
        fb.className = 'feedback err';
        fb.textContent = `Refresh failed: ${err.message}`;
        fb.style.display = 'block';
      } finally {
        btn.disabled = false;
        btn.textContent = prevText;
      }
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
        this._renderWallScenePicker();
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
        this._renderWallScenePicker();
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
      // Clicking the empty space around the photo (the greyed-out stage,
      // or the overlay's own margins) closes the viewer -- the standard
      // lightbox dismissal. Clicks on the image itself and the nav arrows
      // have their own targets and don't match.
      root.getElementById('pack-preview-stage').addEventListener('click', (e) => {
        if (e.target.id === 'pack-preview-stage') this._closePackPreview();
      });
      root.getElementById('pack-preview-overlay').addEventListener('click', (e) => {
        if (e.target.id === 'pack-preview-overlay') this._closePackPreview();
      });

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
        if (result.queued) {
          // Frame hasn't actually received the image yet -- don't
          // optimistically update lastImageId, only for immediate sends.
          this._editorShowFb('ok', '⏳ Frame is asleep — image queued, will send when it wakes.');
          setTimeout(() => this._closeEditor(), 1800);
        } else if (!resp.ok || !result.success) {
          throw new Error(result.message || resp.statusText || `HTTP ${resp.status}`);
        } else {
          const sentFrame = this._frames.find(f => f.entityId === entityId);
          if (sentFrame) {
            sentFrame.lastImageId = st.image.image_id;
            this._renderFrames();
          }
          this._editorShowFb('ok', result.packer ? `✓ Sent! (packer: ${result.packer})` : '✓ Sent!');
          setTimeout(() => this._closeEditor(), 1200);
        }
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
