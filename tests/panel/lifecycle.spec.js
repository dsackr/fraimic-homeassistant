// Element lifecycle coverage: removing the panel from the DOM (an HA panel
// navigation) must sever its window/document listeners and release its blob
// URLs; a same-tick detach/reattach (a DOM move) must not tear anything
// down; and a real reattach must put the panel back in working order.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
];

// Selecting scene_1 previews its mapping on the wall canvas -- its one
// mapped frame (entry_1) sits on the default wall (every configured frame
// does), so the thumbnail paints on its canvas tile.
async function openScenesTabAndWaitForCover(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="dashboard"]').click();
  });
  await page.waitForFunction(() => {
    const sel = document.getElementById('panel').shadowRoot.getElementById('wall-scene-select');
    return [...sel.options].some((o) => o.value === 'scene_1');
  }, { timeout: 5000 });
  await page.evaluate(() => {
    const sel = document.getElementById('panel').shadowRoot.getElementById('wall-scene-select');
    sel.value = 'scene_1';
    sel.dispatchEvent(new Event('change'));
  });
  await page.waitForFunction(() => {
    const img = document.getElementById('panel').shadowRoot.querySelector('.wall-tile img');
    return img && img.src.startsWith('blob:');
  }, { timeout: 5000 });
  return page.evaluate(() =>
    document.getElementById('panel').shadowRoot.querySelector('.wall-tile img').src
  );
}

test.describe('Panel element lifecycle', () => {
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

  test('detach disposes (listeners severed, blobs revoked); reattach revives', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    const srcBefore = await openScenesTabAndWaitForCover(page);

    // Stash a reference so the detached element stays reachable.
    await page.evaluate(() => { window.__panel = document.getElementById('panel'); });

    await page.evaluate(() => window.__panel.remove());
    await page.waitForTimeout(100);

    const afterDetach = await page.evaluate(() => ({
      disposed: window.__panel._disposed,
      aborted: window.__panel._abort.signal.aborted,
      thumbCount: Object.keys(window.__panel._thumbUrls).length,
      queueLen: window.__panel._thumbQueue.length,
    }));
    expect(afterDetach.disposed).toBe(true);
    expect(afterDetach.aborted).toBe(true);
    expect(afterDetach.thumbCount).toBe(0);
    expect(afterDetach.queueLen).toBe(0);

    // Global events while detached must be inert (severed listeners).
    await page.evaluate(() => {
      window.dispatchEvent(new Event('focus'));
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Reattach: panel revives and the wall tile's thumbnail repaints with
    // a fresh blob.
    await page.evaluate(() => document.body.appendChild(window.__panel));
    const revived = await page.evaluate(() => ({
      disposed: window.__panel._disposed,
      aborted: window.__panel._abort.signal.aborted,
    }));
    expect(revived.disposed).toBe(false);
    expect(revived.aborted).toBe(false);

    await page.waitForFunction(() => {
      const img = window.__panel.shadowRoot.querySelector('.wall-tile img');
      return img && img.src.startsWith('blob:');
    }, { timeout: 5000 });

    expect(pageErrors).toEqual([]);
  });

  test('a same-tick DOM move does not dispose anything', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    const srcBefore = await openScenesTabAndWaitForCover(page);

    await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const wrapper = document.createElement('div');
      document.body.appendChild(wrapper);
      wrapper.appendChild(panel); // detach + reattach in one tick
    });
    await page.waitForTimeout(100);

    const state = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const img = panel.shadowRoot.querySelector('.wall-tile img');
      return {
        disposed: panel._disposed,
        thumbCount: Object.keys(panel._thumbUrls).length,
        imgSrc: img ? img.src : null,
      };
    });
    expect(state.disposed).toBe(false);
    expect(state.thumbCount).toBeGreaterThan(0);
    // Same blob URL -- nothing was revoked or re-fetched.
    expect(state.imgSrc).toBe(srcBefore);

    expect(pageErrors).toEqual([]);
  });
});
