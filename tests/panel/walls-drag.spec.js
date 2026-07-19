// Regression coverage for the Walls drag-and-drop bug fixed in commit
// 129835b: digital-frames-panel.js has a top-level `const CSS` (its stylesheet
// text) that shadows the global CSS object for the whole file, so
// CSS.escape() -- used to look up a placed tile by entry_id -- threw
// immediately and silently killed every drag. If that regresses, these
// tests fail via a thrown pageerror and/or no tile ever appearing.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  dragTileBy,
  getWallTiles,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'auto' },
];

let mockServer;
let baseUrl;

test.beforeEach(async () => {
  mockServer = createMockServer({ frames: FRAMES });
  baseUrl = await mockServer.start();
});

test.afterEach(async () => {
  await mockServer.stop();
});

test('dragging a frame from the palette places it on the canvas', async ({ page }) => {
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });

  await dragFirstPaletteItemTo(page, canvasBox.x + 120, canvasBox.y + 100);
  await page.waitForTimeout(200);

  expect(pageErrors, `unexpected browser errors: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);

  const tiles = await getWallTiles(page);
  expect(tiles).toHaveLength(1);
  expect(tiles[0].entryId).toBe('entry_1');

  const placements = await page.evaluate(() => document.getElementById('panel')._wallPlacements);
  expect(placements.entry_1).toBeTruthy();
  expect(placements.entry_1.x).toBeGreaterThanOrEqual(0);
  expect(placements.entry_1.y).toBeGreaterThanOrEqual(0);

  const paletteCount = await page.evaluate(
    () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-palette-item').length
  );
  expect(paletteCount).toBe(1); // the placed frame drops out of the palette
});

test('dragging a placed tile repositions it instead of re-adding it', async ({ page }) => {
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
  await dragFirstPaletteItemTo(page, canvasBox.x + 60, canvasBox.y + 40);
  await page.waitForTimeout(150);

  const before = (await getWallTiles(page))[0];
  await dragTileBy(page, 'entry_1', 150, 80);
  await page.waitForTimeout(150);

  expect(pageErrors).toHaveLength(0);

  const tiles = await getWallTiles(page);
  expect(tiles).toHaveLength(1); // still one tile, not a second one
  expect(tiles[0].left).not.toBe(before.left);
  expect(tiles[0].top).not.toBe(before.top);
});

test('clicking the remove button on a placed tile removes it from the canvas', async ({ page }) => {
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });

  await dragFirstPaletteItemTo(page, canvasBox.x + 120, canvasBox.y + 100);
  await page.waitForTimeout(200);

  let tiles = await getWallTiles(page);
  expect(tiles).toHaveLength(1);

  // Click the remove button
  await page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    const btn = root.querySelector('.tile-remove-btn');
    btn.click();
  });
  await page.waitForTimeout(200);

  tiles = await getWallTiles(page);
  expect(tiles).toHaveLength(0); // removed!

  const paletteCount = await page.evaluate(
    () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-palette-item').length
  );
  expect(paletteCount).toBe(2); // both frames back in palette
});
