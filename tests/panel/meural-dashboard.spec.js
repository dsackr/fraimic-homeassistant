// KPF 32: Meural frames have no battery sensor — panel discovery must use
// the `_ip` send-entity fallback so they appear on the Frames dashboard.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, getWallTiles, getWallPaletteItems } = require('./fixtures/panel-page');

const FRAMES = [
  {
    entry_id: 'entry_fraimic',
    title: 'Living Room Fraimic',
    width: 1200,
    height: 1600,
    orientation: 'auto',
  },
  {
    entry_id: 'entry_meural',
    title: 'Kitchen Meural',
    width: 1920,
    height: 1080,
    orientation: 'auto',
    send_entity: 'ip',
    host: '192.168.1.32',
    origin: 'meural',
    driver: 'meural',
  },
];

test.describe('Meural on dashboard (ip send entity)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Meural with only _ip sensor is discovered and shown with Fraimic frames', async ({ page }) => {
    const discovered = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      return panel._frames.map((f) => ({
        entryId: f.entryId,
        title: f.title,
        entityId: f.entityId,
      }));
    });

    expect(discovered).toEqual([
      {
        entryId: 'entry_fraimic',
        title: 'Living Room Fraimic',
        entityId: 'sensor.entry_fraimic_battery',
      },
      {
        entryId: 'entry_meural',
        title: 'Kitchen Meural',
        entityId: 'sensor.entry_meural_ip',
      },
    ]);

    // Default wall places every frame; both tiles (or palette items) present.
    const tiles = await getWallTiles(page);
    const palette = await getWallPaletteItems(page);
    const entryIds = new Set([
      ...tiles.map((t) => t.entryId),
      ...palette.map((p) => p.entryId),
    ]);
    expect(entryIds.has('entry_fraimic')).toBe(true);
    expect(entryIds.has('entry_meural')).toBe(true);
  });
});
