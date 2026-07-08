// Regression coverage for lazy thumbnail loading: grid tiles fetch their
// thumbnail only when they (can) come into view. A hidden tab's grid is
// display:none, which never intersects, so e.g. the wall canvas/palette's
// thumbnails must not cost any network at init -- they load once the Scenes
// tab is open AND a scene mapping is actually selected.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
];

function imageFetches(mockServer, imageId) {
  return mockServer.requestLog.filter((r) => r.includes(`/library/image/${imageId}`)).length;
}

test.describe('Lazy thumbnail loading', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      albums: [],
      scenes: [{ scene_id: 'scene_1', name: 'Test Scene', mappings: { entry_1: 'image_1' } }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('hidden-tab thumbnails are not fetched at init, only once selected', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    // Give any (wrong) eager fetch time to fire. The wall canvas tile's
    // thumbnail is the only _loadThumbnail consumer in this fixture (the
    // frame sits on the default wall), and it lives in the hidden Scenes
    // tab -- and isn't even showing an image yet, since no scene is
    // selected by default ("Create New…").
    await page.waitForTimeout(400);
    expect(imageFetches(mockServer, 'image_1')).toBe(0);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="scenes"]').click();
    });
    await page.waitForTimeout(200);
    expect(imageFetches(mockServer, 'image_1')).toBe(0); // tab open, but still no scene selected

    await page.waitForFunction(() => {
      const sel = document.getElementById('panel').shadowRoot.getElementById('wall-scene-select');
      return [...sel.options].some((o) => o.value === 'scene_1');
    }, { timeout: 5000 });
    await page.evaluate(() => {
      const sel = document.getElementById('panel').shadowRoot.getElementById('wall-scene-select');
      sel.value = 'scene_1';
      sel.dispatchEvent(new Event('change'));
    });

    // Now the tile thumbnail is showing: the observer fires and it loads.
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return !!root.querySelector('.wall-tile img');
    }, { timeout: 5000 });
    expect(imageFetches(mockServer, 'image_1')).toBe(1);
  });
});
