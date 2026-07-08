// Coverage for the default-wall layout interactions: tiles can never
// overlap (a colliding drag reverts, a colliding palette-drop cancels), a
// selected tile nudges by one grid unit with the arrow keys (collision =
// no-op, never a shove), and every layout change auto-saves.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openScenesTab, dragTileBy, dragFirstPaletteItemTo, clickTile, getWallTiles } = require('./fixtures/panel-page');

// Same aspect (1200x1600 → 105x140 tiles), seeded side by side with one
// 20px grid column between them.
const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const DEFAULT_WALL = {
  wall_id: 'default', name: 'All Frames', kind: 'default',
  placements: { entry_1: { x: 0, y: 0 }, entry_2: { x: 160, y: 0 } },
};

async function tilePos(page, entryId) {
  const tiles = await getWallTiles(page);
  const t = tiles.find((x) => x.entryId === entryId);
  return { x: parseFloat(t.left), y: parseFloat(t.top) };
}

async function selectTileWithoutPicker(page, entryId) {
  await clickTile(page, entryId);
  // The click also opens the image picker -- close it so keydown guards
  // don't ignore the arrows.
  await page.evaluate(() => {
    const panel = document.getElementById('panel');
    panel._closeWallImagePicker();
  });
}

test.describe('Default wall collision and keyboard nudge', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, walls: [DEFAULT_WALL] });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-tile').length === 2
    );
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('dragging a tile onto another reverts to its start position', async ({ page }) => {
    const before = await tilePos(page, 'entry_1');
    // Drop entry_1 squarely onto entry_2 (160px right).
    await dragTileBy(page, 'entry_1', 160, 0);
    const after = await tilePos(page, 'entry_1');
    expect(after).toEqual(before);

    // And no save was scheduled for the rejected move.
    await page.waitForTimeout(1000);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_1).toEqual({ x: 0, y: 0 });
  });

  test('a legal drag snaps to the grid and auto-saves', async ({ page }) => {
    await dragTileBy(page, 'entry_1', 0, 200);
    const after = await tilePos(page, 'entry_1');
    expect(after.y).toBeGreaterThan(0);
    expect(after.x % 20).toBe(0);
    expect(after.y % 20).toBe(0);

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_1).toEqual({ x: after.x, y: after.y });
  });

  test('arrow keys nudge the selected tile by one grid unit and auto-save', async ({ page }) => {
    await selectTileWithoutPicker(page, 'entry_1');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowRight');

    const after = await tilePos(page, 'entry_1');
    expect(after).toEqual({ x: 20, y: 40 });

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_1).toEqual({ x: 20, y: 40 });
  });

  test('a nudge into a neighboring tile is a no-op, not a shove', async ({ page }) => {
    // entry_1 tile is 105px wide at x=0; entry_2 sits at x=160. Three
    // right-nudges are legal (x=60: 60+105=165 > 160 collides!) -- so the
    // second nudge (x=40 → 40+105=145 < 160 ok) then third (x=60) collides.
    await selectTileWithoutPicker(page, 'entry_1');
    await page.keyboard.press('ArrowRight'); // x=20 ok
    await page.keyboard.press('ArrowRight'); // x=40 ok
    await page.keyboard.press('ArrowRight'); // x=60 would overlap -> no-op

    const pos1 = await tilePos(page, 'entry_1');
    const pos2 = await tilePos(page, 'entry_2');
    expect(pos1).toEqual({ x: 40, y: 0 });
    expect(pos2).toEqual({ x: 160, y: 0 }); // neighbor never moved
  });

  test('the realistic path works: click tile, dismiss picker by clicking outside, arrows nudge', async ({ page }) => {
    await clickTile(page, 'entry_1');
    // The picker opens async (it fetches albums first) -- wait for its
    // backdrop before "clicking outside", or the click lands on the empty
    // canvas instead, which deselects (the multi-select clear gesture).
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );
    // The picker's transparent backdrop covers the viewport -- clicking
    // anywhere outside its box is how a user dismisses it.
    await page.mouse.click(600, 500);
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');

    const pos = await tilePos(page, 'entry_1');
    expect(pos).toEqual({ x: 0, y: 40 });
  });

  test('Escape closes the picker first (keeping the selection), then clears the selection', async ({ page }) => {
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );

    await page.keyboard.press('Escape');
    const afterFirst = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      return {
        pickerDisplay: panel.shadowRoot.getElementById('wall-image-picker-overlay').style.display,
        selected: [...panel._wallSelection][0] || null,
      };
    });
    expect(afterFirst.pickerDisplay).toBe('none');
    expect(afterFirst.selected).toBe('entry_1');

    // Arrows still work right after dismissing the picker with Escape --
    // regression for the trap where Escape killed the selection instead.
    await page.keyboard.press('ArrowDown');
    expect(await tilePos(page, 'entry_1')).toEqual({ x: 0, y: 20 });

    await page.keyboard.press('Escape');
    const selected = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      return [...panel._wallSelection][0] || null;
    });
    expect(selected).toBe(null);
  });

  test('✕ removes a tile from the default wall, tombstoned so auto-sync stays away', async ({ page }) => {
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      [...root.querySelectorAll('.wall-tile')]
        .find((t) => t.dataset.entryId === 'entry_1')
        .querySelector('.tile-remove-btn').click();
    });

    // Gone from the canvas, back in the palette.
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelectorAll('.wall-tile').length === 1
        && root.querySelectorAll('.wall-palette-item').length === 1;
    });

    // The auto-save records the tombstone alongside the placements.
    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(Object.keys(saved.placements)).toEqual(['entry_2']);
    expect(saved.excluded).toEqual(['entry_1']);

    // Dragging it back on lifts the tombstone.
    const canvasBox = await page.evaluate(() => {
      const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
      return { x: r.x, y: r.y };
    });
    await dragFirstPaletteItemTo(page, canvasBox.x + 60, canvasBox.y + 240);
    await page.waitForTimeout(1200);
    const resaved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(Object.keys(resaved.placements).sort()).toEqual(['entry_1', 'entry_2']);
    expect(resaved.excluded).toEqual([]);
  });

  test('dragging a tile off the canvas removes it from the wall', async ({ page }) => {
    // Drag entry_1 far above the canvas -- well outside its bounds.
    const tileBox = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === 'entry_1');
      const r = tile.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await page.mouse.move(tileBox.x, tileBox.y);
    await page.mouse.down();
    await page.mouse.move(tileBox.x + 20, tileBox.y - 30, { steps: 5 });
    await page.mouse.move(tileBox.x + 40, 5, { steps: 10 });   // above the header, off-canvas
    await page.mouse.up();

    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelectorAll('.wall-tile').length === 1
        && root.querySelectorAll('.wall-palette-item').length === 1;
    });

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(Object.keys(saved.placements)).toEqual(['entry_2']);
    expect(saved.excluded).toEqual(['entry_1']);
  });

  test('Escape clears the selection so arrows stop nudging', async ({ page }) => {
    await selectTileWithoutPicker(page, 'entry_1');
    await page.keyboard.press('Escape');
    await page.keyboard.press('ArrowDown');

    const pos = await tilePos(page, 'entry_1');
    expect(pos).toEqual({ x: 0, y: 0 });
    const selected = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-tile.selected').length
    );
    expect(selected).toBe(0);
  });
});
