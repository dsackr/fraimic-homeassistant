// Coverage for the consolidated dashboard: two tabs only (Dashboard is the
// default and hosts the wall canvas), the header's Manage Library and
// Settings modals, tile footers (name + live status), send-on-pick, and the
// per-tile "Upload a photo" raw-send path.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickTile, pickImageInWallPicker } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
];

test.describe('Consolidated dashboard', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Dashboard is the default (and only) content tab beside Add-ons', async ({ page }) => {
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        tabs: [...root.querySelectorAll('.tab-btn')].map((b) => b.dataset.tab),
        activeContent: root.getElementById('tab-dashboard').classList.contains('active'),
        headerButtons: ['frame-add-btn', 'library-open-btn', 'settings-open-btn']
          .map((id) => !!root.getElementById(id)),
      };
    });
    expect(state.tabs).toEqual(['dashboard', 'addons']);
    expect(state.activeContent).toBe(true);
    expect(state.headerButtons).toEqual([true, true, true]);
  });

  test('tiles carry a footer with the frame name and live status', async ({ page }) => {
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const status = root.querySelector('.wall-tile [data-status-entity]');
      return status && status.textContent.length > 0;
    }, { timeout: 5000 });

    const footer = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = root.querySelector('.wall-tile');
      return {
        name: tile.querySelector('.wall-tile-name').textContent,
        status: tile.querySelector('.wall-tile-status').textContent,
        hasGear: !!tile.querySelector('.wall-tile-gear'),
      };
    });
    expect(footer.name).toBe('Living Room Frame');
    expect(footer.status).toContain('🔋90%');   // battery from the mock hass state
    expect(footer.hasGear).toBe(true);
  });

  test('Manage Library opens as a modal and the upload sub-modal stacks above it', async ({ page }) => {
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('library-open-btn').click();
    });
    const libOpen = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.getElementById('library-modal-overlay').style.display;
    });
    expect(libOpen).toBe('flex');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('lib-upload-btn').click();
    });
    const stacking = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const lib = root.getElementById('library-modal-overlay');
      const upload = root.getElementById('upload-modal-overlay');
      return {
        uploadOpen: upload.style.display === 'flex',
        libZ: parseInt(getComputedStyle(lib).zIndex, 10),
        uploadZ: parseInt(getComputedStyle(upload).zIndex, 10),
      };
    });
    expect(stacking.uploadOpen).toBe(true);
    expect(stacking.uploadZ).toBeGreaterThan(stacking.libZ);
  });

  test('Settings opens with the current backend selected', async ({ page }) => {
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('settings-open-btn').click();
    });
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        open: root.getElementById('settings-modal-overlay').style.display === 'flex',
        backend: root.getElementById('backend-select').value,
        configText: root.getElementById('backend-config').textContent,
      };
    });
    expect(state.open).toBe(true);
    expect(state.backend).toBe('local');
    expect(state.configText).toContain('local storage');
  });

  test('picking a library image sends it to the frame immediately', async ({ page }) => {
    await clickTile(page, 'entry_1');
    await pickImageInWallPicker(page, 'image_1');

    await expect.poll(() => mockServer.sends.map((s) => ({ entity_id: s.entity_id, image_id: s.image_id })))
      .toEqual([{ entity_id: 'sensor.entry_1_battery', image_id: 'image_1' }]);

    // The scene-staging side is untouched: the pick is also a pending
    // mapping, so Save Scene keeps working on top of immediate sends.
    const pending = await page.evaluate(
      () => document.getElementById('panel')._wallPendingMappings
    );
    expect(pending).toEqual({ entry_1: 'image_1' });
  });

  test('the picker "Upload a photo" posts the file straight to send_image', async ({ page }) => {
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );

    const input = await page.evaluateHandle(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-picker-upload-input')
    );
    await input.asElement().setInputFiles({
      name: 'photo.png',
      mimeType: 'image/png',
      buffer: Buffer.from('89504e470d0a1a0a', 'hex'),
    });

    await expect.poll(() => mockServer.rawSends)
      .toEqual([{ entity_id: 'sensor.entry_1_battery', has_image: true }]);

    // The picker closed itself after handing the file off.
    const pickerDisplay = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display
    );
    expect(pickerDisplay).toBe('none');
  });
});
