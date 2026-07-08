// Multi-select on the wall canvas: shift-click and rubber-band drag build a
// selection, arrow keys and mouse drags move the whole group as one
// (all-or-nothing, never a shove), and the align toolbar lines selected
// tiles up on any edge or midline -- rejecting with a message when the
// result would overlap.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openScenesTab, clickTile, getWallTiles } = require('./fixtures/panel-page');

// Same aspect (1200x1600 → 105x140 tiles), three across with a 20px grid
// column between neighbors, entry_3 dropped lower for alignment tests.
const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_3', title: 'Hall Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const DEFAULT_WALL = {
  wall_id: 'default', name: 'All Frames', kind: 'default',
  placements: {
    entry_1: { x: 0, y: 0 },
    entry_2: { x: 160, y: 0 },
    entry_3: { x: 320, y: 60 },
  },
};

async function tilePos(page, entryId) {
  const tiles = await getWallTiles(page);
  const t = tiles.find((x) => x.entryId === entryId);
  return { x: parseFloat(t.left), y: parseFloat(t.top) };
}

async function shiftClickTile(page, entryId) {
  await page.keyboard.down('Shift');
  await clickTile(page, entryId);
  await page.keyboard.up('Shift');
}

function getSelection(page) {
  return page.evaluate(() => [...document.getElementById('panel')._wallSelection].sort());
}

function pickerDisplay(page) {
  return page.evaluate(
    () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display
  );
}

async function clickAlign(page, mode) {
  await page.evaluate((m) => {
    document.getElementById('panel').shadowRoot
      .querySelector(`#wall-align-toolbar [data-align="${m}"]`).click();
  }, mode);
}

function canvasRect(page) {
  return page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
}

test.describe('Wall multi-select, group move, and align', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, walls: [DEFAULT_WALL] });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-tile').length === 3
    );
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('shift-click builds a selection without opening the picker; plain click collapses it', async ({ page }) => {
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');
    expect(await getSelection(page)).toEqual(['entry_1', 'entry_2']);
    expect(await pickerDisplay(page)).not.toBe('block');

    // The align toolbar appears with 2+ selected.
    const toolbar = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        display: root.getElementById('wall-align-toolbar').style.display,
        count: root.getElementById('wall-align-count').textContent,
      };
    });
    expect(toolbar.display).toBe('flex');
    expect(toolbar.count).toContain('2 frames');

    // Shift-click again toggles back out.
    await shiftClickTile(page, 'entry_2');
    expect(await getSelection(page)).toEqual(['entry_1']);

    // A plain click always collapses to a single selection + picker.
    await shiftClickTile(page, 'entry_2');
    await clickTile(page, 'entry_3');
    expect(await getSelection(page)).toEqual(['entry_3']);
    expect(await pickerDisplay(page)).toBe('block');
  });

  test('a rubber-band drag on empty canvas selects the swept tiles; empty click clears', async ({ page }) => {
    const rect = await canvasRect(page);
    // Sweep from below the tiles up over entry_1 (x 0-105) and entry_2
    // (x 160-265) but stopping short of entry_3 (x 320+).
    await page.mouse.move(rect.x + 290, rect.y + 300);
    await page.mouse.down();
    await page.mouse.move(rect.x + 2, rect.y + 2, { steps: 8 });
    await page.mouse.up();
    expect(await getSelection(page)).toEqual(['entry_1', 'entry_2']);

    // A plain click on empty canvas clears the selection.
    await page.mouse.click(rect.x + 500, rect.y + 350);
    expect(await getSelection(page)).toEqual([]);
  });

  test('arrow keys move the whole selection as one and auto-save', async ({ page }) => {
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowRight');

    expect(await tilePos(page, 'entry_1')).toEqual({ x: 20, y: 40 });
    expect(await tilePos(page, 'entry_2')).toEqual({ x: 180, y: 40 });
    expect(await tilePos(page, 'entry_3')).toEqual({ x: 320, y: 60 }); // not selected, never moved

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_1).toEqual({ x: 20, y: 40 });
    expect(saved.placements.entry_2).toEqual({ x: 180, y: 40 });
  });

  test('a group nudge that would hit an unselected neighbor is a no-op for the whole group', async ({ page }) => {
    // entry_2 (x=160, 105 wide) marching right toward entry_3 at x=320:
    // +20 → 180 (right edge 285 < 320, ok), +20 → 200 (305 < 320, ok),
    // +20 → 220 would reach 325 > 320 → blocked for BOTH tiles.
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');

    expect(await tilePos(page, 'entry_1')).toEqual({ x: 40, y: 0 });
    expect(await tilePos(page, 'entry_2')).toEqual({ x: 200, y: 0 });
    expect(await tilePos(page, 'entry_3')).toEqual({ x: 320, y: 60 });
  });

  test('dragging one member of the selection moves the whole group, offsets preserved', async ({ page }) => {
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');

    // Drag entry_1 down by ~200px with real pointer events.
    const start = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === 'entry_1');
      const r = tile.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(start.x + 10, start.y + 100, { steps: 5 });
    await page.mouse.move(start.x, start.y + 200, { steps: 5 });
    await page.mouse.up();

    const p1 = await tilePos(page, 'entry_1');
    const p2 = await tilePos(page, 'entry_2');
    expect(p1.y).toBeGreaterThan(0);
    expect(p1.x % 20).toBe(0);
    expect(p1.y % 20).toBe(0);
    // The formation held: entry_2 stayed exactly 160 right of entry_1.
    expect(p2.x - p1.x).toBe(160);
    expect(p2.y - p1.y).toBe(0);
    // Both stayed selected for further nudging/aligning.
    expect(await getSelection(page)).toEqual(['entry_1', 'entry_2']);

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_1).toEqual(p1);
    expect(saved.placements.entry_2).toEqual(p2);
  });

  test('align top and align left line the selection up on its outermost edge', async ({ page }) => {
    // entry_2 (y=0) and entry_3 (y=60) → align top pulls entry_3 to y=0.
    await shiftClickTile(page, 'entry_2');
    await shiftClickTile(page, 'entry_3');
    await clickAlign(page, 'top');
    expect(await tilePos(page, 'entry_2')).toEqual({ x: 160, y: 0 });
    expect(await tilePos(page, 'entry_3')).toEqual({ x: 320, y: 0 });

    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    expect(saved.placements.entry_3).toEqual({ x: 320, y: 0 });
  });

  test('align bottom with mixed vertical positions uses the lowest bottom edge', async ({ page }) => {
    // entry_2 bottom = 140, entry_3 bottom = 60+140 = 200 → both bottoms at 200.
    await shiftClickTile(page, 'entry_2');
    await shiftClickTile(page, 'entry_3');
    await clickAlign(page, 'bottom');
    expect(await tilePos(page, 'entry_2')).toEqual({ x: 160, y: 60 });
    expect(await tilePos(page, 'entry_3')).toEqual({ x: 320, y: 60 });
  });

  test('an align that would overlap is rejected with a message and nothing moves', async ({ page }) => {
    // entry_1 (x=0) and entry_2 (x=160) share y=0: aligning left edges
    // would stack them into each other.
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');
    await clickAlign(page, 'left');

    expect(await tilePos(page, 'entry_1')).toEqual({ x: 0, y: 0 });
    expect(await tilePos(page, 'entry_2')).toEqual({ x: 160, y: 0 });
    const fb = await page.evaluate(() => {
      const el = document.getElementById('panel').shadowRoot.getElementById('wall-fb');
      return { text: el.textContent, className: el.className };
    });
    expect(fb.className).toContain('err');
    expect(fb.text).toContain('would overlap');
  });

  test('Escape clears a multi-selection and hides the align toolbar', async ({ page }) => {
    await shiftClickTile(page, 'entry_1');
    await shiftClickTile(page, 'entry_2');
    await page.keyboard.press('Escape');
    expect(await getSelection(page)).toEqual([]);
    const display = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-align-toolbar').style.display
    );
    expect(display).toBe('none');
  });
});
