// Regression coverage for lazy thumbnail loading: grid tiles fetch their
// thumbnail only when they (can) come into view. A hidden tab's grid is
// display:none, which never intersects, so e.g. scene covers must not cost
// any network at init -- they load when the Scenes tab is first opened.

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

  test('hidden-tab thumbnails are not fetched at init, only when the tab opens', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    // Give any (wrong) eager fetch time to fire. The scene card's cover is
    // the only _loadThumbnail consumer in this fixture, and it lives in the
    // hidden Scenes tab.
    await page.waitForTimeout(400);
    expect(imageFetches(mockServer, 'image_1')).toBe(0);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="scenes"]').click();
    });

    // Now the grid is visible: the observer fires and the cover loads.
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const thumb = root.querySelector('#scene-grid .lib-thumb img');
      return !!thumb;
    }, { timeout: 5000 });
    expect(imageFetches(mockServer, 'image_1')).toBe(1);
  });
});
