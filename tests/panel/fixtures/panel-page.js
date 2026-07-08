// Shared setup for driving <fraimic-panel> in a real browser against a
// createMockServer() backend. Keeps each spec focused on the flow it's
// actually testing instead of re-deriving init/navigation boilerplate.

// `query` (e.g. '?packtest') lands in the harness page's URL, which the
// panel reads via window.location.search -- same as HA's real panel iframe.
async function gotoPanel(page, baseUrl, { frames = [], query = '' } = {}) {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err));

  await page.goto(`${baseUrl}/harness.html${query}`);
  await page.evaluate((frameList) => {
    document.getElementById('panel').hass = window.__buildMockHass(frameList);
  }, frames);

  await page.waitForFunction(
    (expectedFrameCount) => {
      const panel = document.getElementById('panel');
      return panel && panel._frames && panel._frames.length === expectedFrameCount && panel._loaded;
    },
    frames.length,
    { timeout: 10000 }
  );

  return { pageErrors };
}

// The Dashboard tab (default) *is* the wall canvas. Kept as an explicit
// helper (and under its historical openScenesTab name) so specs stay
// readable and are robust to the default tab ever changing.
async function openDashboard(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="dashboard"]').click();
  });
}
const openScenesTab = openDashboard;

// Creates a wall via the "New Wall" button, auto-answering the name prompt.
async function createWall(page, name) {
  page.once('dialog', (dialog) => dialog.accept(name));
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.getElementById('wall-new-btn').click();
  });
  await page.waitForFunction(() => {
    const panel = document.getElementById('panel');
    return panel._activeWallId && panel._walls.some((w) => w.wall_id === panel._activeWallId);
  }, { timeout: 10000 });
}

// Drags the first not-yet-placed palette item onto the canvas at (dropX, dropY)
// in page (viewport) coordinates. Uses real mouse events, not a synthetic
// drag-and-drop API, since that's what the panel's pointerdown/move/up
// handlers actually listen for.
async function dragFirstPaletteItemTo(page, dropX, dropY) {
  const paletteBox = await page.evaluate(() => {
    const item = document.getElementById('panel').shadowRoot.querySelector('.wall-palette-item');
    const r = item.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.move(paletteBox.x, paletteBox.y);
  await page.mouse.down();
  await page.mouse.move(paletteBox.x + 20, paletteBox.y + 10, { steps: 5 });
  await page.mouse.move(dropX, dropY, { steps: 10 });
  await page.mouse.up();
}

async function dragTileBy(page, entryId, dx, dy) {
  const tileBox = await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    const r = tile.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  }, entryId);
  await page.mouse.move(tileBox.x, tileBox.y);
  await page.mouse.down();
  await page.mouse.move(tileBox.x + 20, tileBox.y + 10, { steps: 5 });
  await page.mouse.move(tileBox.x + dx, tileBox.y + dy, { steps: 10 });
  await page.mouse.up();
}

// A tile click (no movement) opens that tile's image picker rather than
// "repositioning" it -- see _onWallPointerUp's `!drag.moved` check.
async function clickTile(page, entryId) {
  const box = await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    const r = tile.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  }, entryId);
  await page.mouse.move(box.x, box.y);
  await page.mouse.down();
  await page.mouse.up();
}

// Same as clickTile, but for a frame still sitting in the palette (not
// placed on the canvas) -- a frame works the same on or off the wall, so
// this also opens the image picker instead of "placing" it.
async function clickPaletteItem(page, entryId) {
  const box = await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const item = [...root.querySelectorAll('.wall-palette-item')].find((t) => t.dataset.entryId === id);
    const r = item.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  }, entryId);
  await page.mouse.move(box.x, box.y);
  await page.mouse.down();
  await page.mouse.up();
}

async function pickImageInWallPicker(page, imageId) {
  // The picker opens synchronously but populates its grid after an async
  // library fetch -- wait for the target cell to exist before clicking it.
  await page.waitForFunction(
    (id) => !!document
      .getElementById('panel').shadowRoot
      .querySelector(`#wall-image-picker-grid .image-picker-cell[data-image-id="${id}"]`),
    imageId,
    { timeout: 5000 }
  );
  // Clicking a cell only stages the pick (nothing sends until the picker's
  // Send button); close the picker afterwards so specs keep the historical
  // "pick = stage + dismiss" shape.
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const cell = [...root.querySelectorAll('#wall-image-picker-grid .image-picker-cell')].find((c) => c.dataset.imageId === id);
    cell.click();
    document.getElementById('panel')._closeWallImagePicker();
  }, imageId);
}

function getPickerGridImageIds(page) {
  return page.evaluate(() =>
    [...document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
      .map((c) => c.dataset.imageId)
  );
}

async function selectPickerAlbum(page, albumName) {
  await page.evaluate((name) => {
    const root = document.getElementById('panel').shadowRoot;
    const sel = root.getElementById('wall-image-picker-album');
    sel.value = name;
    sel.dispatchEvent(new Event('change'));
  }, albumName);
}

function getPickerBoxRect(page) {
  return page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-box').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
}

// Drags the picker panel by its header -- regression coverage for it being
// stuck in place and blocking the wall behind it.
async function dragPickerBy(page, dx, dy) {
  const header = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-header').getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + 10 };
  });
  await page.mouse.move(header.x, header.y);
  await page.mouse.down();
  await page.mouse.move(header.x + dx / 2, header.y + dy / 2, { steps: 5 });
  await page.mouse.move(header.x + dx, header.y + dy, { steps: 10 });
  await page.mouse.up();
}

async function selectWallScene(page, sceneId) {
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const sel = root.getElementById('wall-scene-select');
    sel.value = id;
    sel.dispatchEvent(new Event('change'));
  }, sceneId);
}

async function getWallTiles(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    return [...root.querySelectorAll('.wall-tile')].map((t) => ({
      entryId: t.dataset.entryId,
      left: t.style.left,
      top: t.style.top,
      hasImg: !!t.querySelector('img'),
      imgSrc: t.querySelector('img') ? t.querySelector('img').src : null,
    }));
  });
}

async function getWallPaletteItems(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    return [...root.querySelectorAll('.wall-palette-item')].map((item) => ({
      entryId: item.dataset.entryId,
      hasImg: !!item.querySelector('.wall-palette-thumb img'),
    }));
  });
}

async function clickPanelButton(page, id) {
  await page.evaluate((elId) => {
    document.getElementById('panel').shadowRoot.getElementById(elId).click();
  }, id);
}

async function getFeedback(page, id) {
  return page.evaluate((elId) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    return { text: el.textContent, className: el.className, display: el.style.display };
  }, id);
}

module.exports = {
  gotoPanel,
  openDashboard,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  dragTileBy,
  clickTile,
  clickPaletteItem,
  pickImageInWallPicker,
  getPickerGridImageIds,
  selectPickerAlbum,
  getPickerBoxRect,
  dragPickerBy,
  selectWallScene,
  getWallTiles,
  getWallPaletteItems,
  clickPanelButton,
  getFeedback,
};
