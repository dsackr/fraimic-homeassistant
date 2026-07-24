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

test('a second pointerdown before the first drag ends does not leak a ghost element', async ({ page }) => {
  // Regression: _wallBeginDrag had no guard against a pre-existing
  // this._wallDrag -- a second pointerdown (overlapping pointer input:
  // multi-touch/stylus+mouse, common on the touchscreen tablets this
  // dashboard is often wall-mounted on) before the first drag's pointerup
  // overwrote it without removing the first drag's ghost element, leaking
  // it permanently and corrupting which drag the eventual pointerup
  // finalizes.
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  await page.evaluate(() => {
    const item = document.getElementById('panel').shadowRoot.querySelector('.wall-palette-item');
    const r = item.getBoundingClientRect();
    const fire = (x, y) => item.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1,
    }));
    // Two overlapping presses with no pointerup in between.
    fire(r.x + r.width / 2, r.y + r.height / 2);
    fire(r.x + r.width / 2 + 5, r.y + r.height / 2 + 5);
  });

  const ghostCount = await page.evaluate(() =>
    document.getElementById('panel').shadowRoot.querySelectorAll('.wall-drag-ghost').length
  );
  expect(ghostCount).toBe(1);

  // Clean up the still-in-progress drag so it doesn't bleed into other tests.
  await page.mouse.up();
  expect(pageErrors, `unexpected browser errors: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);
});

test('a second marquee-select start before the first ends does not leak a marquee box', async ({ page }) => {
  // Same overlapping-pointer-input hazard as the drag-ghost test above
  // (multi-touch/stylus+mouse, common on the touchscreen tablets this
  // dashboard is often wall-mounted on), but for the rubber-band
  // multi-select path: a second pointerdown on empty canvas space before
  // the first marquee's pointerup used to append a second .wall-marquee
  // box without removing the first, leaking it permanently.
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  await page.evaluate(() => {
    const canvas = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
    const r = canvas.getBoundingClientRect();
    const fire = (x, y) => canvas.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1,
    }));
    // Two overlapping presses on empty canvas space, no pointerup in between.
    fire(r.x + 10, r.y + 10);
    fire(r.x + 20, r.y + 20);
  });

  const marqueeCount = await page.evaluate(() =>
    document.getElementById('panel').shadowRoot.querySelectorAll('.wall-marquee').length
  );
  expect(marqueeCount).toBe(1);

  // Clean up the still-in-progress marquee so it doesn't bleed into other tests.
  await page.mouse.up();
  expect(pageErrors, `unexpected browser errors: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);
});

test('a failed begin-drag with a stale entryId does not cancel an unrelated in-progress drag', async ({ page }) => {
  // Regression: _wallBeginDrag called _wallCancelInProgressDrag() before
  // checking whether entryId resolved to a real frame, so a begin-drag
  // attempt that itself failed (e.g. a pointerdown handler closing over an
  // entryId whose config entry was removed elsewhere before this client's
  // wall view re-rendered) still tore down a different, legitimately
  // in-progress drag as a side effect -- its ghost vanished and the tile
  // reverted even though the interrupting press never started a
  // replacement drag.
  const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
  await openScenesTab(page);
  await createWall(page, 'Living Room');

  await page.evaluate(() => {
    const item = document.getElementById('panel').shadowRoot.querySelector('.wall-palette-item');
    const r = item.getBoundingClientRect();
    item.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, pointerId: 1,
    }));
  });

  const dragEntryIdBefore = await page.evaluate(() => document.getElementById('panel')._wallDrag?.entryId);
  expect(dragEntryIdBefore).toBe('entry_1');

  // A second, unrelated begin-drag attempt whose entryId no longer
  // resolves to a real frame -- must be a true no-op with respect to the
  // drag already in progress.
  await page.evaluate(() => {
    const panel = document.getElementById('panel');
    panel._wallBeginDrag(
      { preventDefault: () => {}, clientX: 0, clientY: 0 },
      'stale_entry_does_not_exist',
      'tile'
    );
  });

  const ghostCount = await page.evaluate(() =>
    document.getElementById('panel').shadowRoot.querySelectorAll('.wall-drag-ghost').length
  );
  expect(ghostCount).toBe(1); // the first drag's ghost must survive

  const dragEntryIdAfter = await page.evaluate(() => document.getElementById('panel')._wallDrag?.entryId);
  expect(dragEntryIdAfter).toBe('entry_1'); // the first drag itself must still be in progress

  await page.mouse.up();
  expect(pageErrors, `unexpected browser errors: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);
});
