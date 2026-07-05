// Coverage for the hidden packer A/B test modal (/fraimic?packtest): it only
// appears when the URL asks for it, and "Go" sends the picked image to Frame A
// with the legacy packer and Frame B with the fast packer, sequentially, each
// send carrying the cache-bypassing packer override.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, getFeedback } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
  { image_id: 'image_2', filename: 'two.png', albums: [] },
];

function overlayDisplay(page) {
  return page.evaluate(() =>
    document.getElementById('panel').shadowRoot.getElementById('packtest-overlay').style.display
  );
}

async function pickPackTestImage(page, imageId) {
  await page.waitForFunction(
    (id) => !!document.getElementById('panel').shadowRoot
      .querySelector(`#packtest-images .image-picker-cell[data-image-id="${id}"]`),
    imageId,
    { timeout: 5000 }
  );
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    [...root.querySelectorAll('#packtest-images .image-picker-cell')]
      .find((c) => c.dataset.imageId === id)
      .click();
  }, imageId);
}

test.describe('Packer A/B test modal', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, albums: [] });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('stays hidden without ?packtest in the URL', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    expect(await overlayDisplay(page)).not.toBe('flex');
  });

  test('opens automatically with ?packtest, frames and images populated', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES, query: '?packtest' });
    await page.waitForFunction(() =>
      document.getElementById('panel').shadowRoot.getElementById('packtest-overlay').style.display === 'flex'
    );

    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        frameAOptions: [...root.getElementById('packtest-frame-a').options].map((o) => o.value),
        frameBValue: root.getElementById('packtest-frame-b').value,
        imageCells: root.querySelectorAll('#packtest-images .image-picker-cell').length,
      };
    });
    // A frame's entityId is its battery sensor -- that's what the send
    // endpoint's resolve_frame_by_entity expects.
    expect(state.frameAOptions).toEqual(['sensor.entry_1_battery', 'sensor.entry_2_battery']);
    // Frame B defaults to a different frame than A.
    expect(state.frameBValue).toBe('sensor.entry_2_battery');
    expect(state.imageCells).toBe(IMAGES.length);
  });

  test('Go sends legacy to Frame A then fast to Frame B, sequentially', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES, query: '?packtest' });
    await page.waitForFunction(() =>
      document.getElementById('panel').shadowRoot.getElementById('packtest-overlay').style.display === 'flex'
    );

    await pickPackTestImage(page, 'image_2');
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('packtest-go').click();
    });

    await page.waitForFunction(() =>
      document.getElementById('panel').shadowRoot.getElementById('packtest-log').textContent.includes('Done.')
    );

    expect(mockServer.sends).toEqual([
      { entity_id: 'sensor.entry_1_battery', image_id: 'image_2', packer: 'legacy' },
      { entity_id: 'sensor.entry_2_battery', image_id: 'image_2', packer: 'fast' },
    ]);

    const log = await page.evaluate(() =>
      document.getElementById('panel').shadowRoot.getElementById('packtest-log').textContent
    );
    expect(log).toContain('legacy packer to "Living Room Frame"');
    expect(log).toContain('fast packer to "Office Frame"');
    expect((log.match(/✓ done/g) || []).length).toBe(2);
  });

  test('refuses to run without an image or with the same frame twice', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES, query: '?packtest' });
    await page.waitForFunction(() =>
      document.getElementById('panel').shadowRoot.getElementById('packtest-overlay').style.display === 'flex'
    );

    // No image picked yet.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('packtest-go').click();
    });
    let fb = await getFeedback(page, 'packtest-fb');
    expect(fb.text).toContain('Pick an image');

    // Same frame on both sides.
    await pickPackTestImage(page, 'image_1');
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('packtest-frame-b').value = root.getElementById('packtest-frame-a').value;
      root.getElementById('packtest-go').click();
    });
    fb = await getFeedback(page, 'packtest-fb');
    expect(fb.text).toContain('two different frames');

    expect(mockServer.sends).toEqual([]);
  });
});
