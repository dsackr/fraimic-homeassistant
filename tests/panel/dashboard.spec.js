// Coverage for the consolidated dashboard: two tabs only (Dashboard is the
// default and hosts the wall canvas), the header's Manage Library and
// Settings modals, tile footers (name + live status), send-on-pick, and the
// per-tile "Upload a photo" raw-send path.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickTile, pickImageInWallPicker } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto', last_image_id: 'image_2' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
  { image_id: 'image_2', filename: 'two.png', albums: [] },
];
const SCENES = [
  { scene_id: 'scene_1', name: 'Test Scene', mappings: { entry_1: 'image_1' } },
];

test.describe('Consolidated dashboard', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, scenes: SCENES });
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

  test('tile badges distinguish scene model from what is merely on the frame', async ({ page }) => {
    const readTile = () => page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = root.querySelector('.wall-tile');
      const badge = tile.querySelector('.wall-tile-badge');
      return {
        badge: badge && badge.style.display !== 'none' ? badge.dataset.kind : null,
        dimmed: !!tile.querySelector('.wall-tile-media.on-frame-only'),
      };
    });

    // No scene selected: the tile shows the frame's current content,
    // dimmed + labeled -- not part of any send model.
    expect(await readTile()).toEqual({ badge: 'onframe', dimmed: true });

    // Selecting a scene: its mapped tile shows the scene image at full
    // strength with a "scene" badge -- the model of what Send will do.
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const sel = root.getElementById('wall-scene-select');
      sel.value = 'scene_1';
      sel.dispatchEvent(new Event('change'));
    });
    expect(await readTile()).toEqual({ badge: 'scene', dimmed: false });

    // A pick this session upgrades the badge to "staged".
    await clickTile(page, 'entry_1');
    await pickImageInWallPicker(page, 'image_2');
    expect(await readTile()).toEqual({ badge: 'staged', dimmed: false });

    // Clear All empties the model everywhere; the tile falls back to the
    // dimmed on-frame view, and nothing was sent anywhere.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-clear-all-btn').click();
    });
    expect(await readTile()).toEqual({ badge: 'onframe', dimmed: true });
    expect(await page.evaluate(() => document.getElementById('panel')._wallPendingMappings))
      .toEqual({ entry_1: '' });
    expect(mockServer.sends).toEqual([]);
    expect(mockServer.rawSends).toEqual([]);
  });

  test('clicking an image only stages it -- the Send button is the transmit moment', async ({ page }) => {
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      (id) => !!document.getElementById('panel').shadowRoot
        .querySelector(`#wall-image-picker-grid .image-picker-cell[data-image-id="${id}"]`),
      'image_1', { timeout: 5000 }
    );
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      [...root.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
        .find((c) => c.dataset.imageId === 'image_1').click();
    });

    // Staged (highlight + pending mapping + enabled Send), NOT sent.
    const staged = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const root = panel.shadowRoot;
      const btn = root.getElementById('wall-picker-send-btn');
      return {
        selected: root.querySelectorAll('#wall-image-picker-grid .image-picker-cell.selected').length,
        pending: panel._wallPendingMappings,
        sendEnabled: !btn.disabled,
        sendLabel: btn.textContent,
      };
    });
    expect(staged.selected).toBe(1);
    expect(staged.pending).toEqual({ entry_1: 'image_1' });
    expect(staged.sendEnabled).toBe(true);
    expect(staged.sendLabel).toContain('Living Room Frame');
    expect(mockServer.sends).toEqual([]);

    // The deliberate click.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-picker-send-btn').click();
    });
    await expect.poll(() => mockServer.sends.map((s) => ({ entity_id: s.entity_id, image_id: s.image_id })))
      .toEqual([{ entity_id: 'sensor.entry_1_battery', image_id: 'image_1' }]);

    // Sending closed the picker.
    const pickerDisplay = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display
    );
    expect(pickerDisplay).toBe('none');
  });

  test('an uploaded photo also stages first and sends only on the Send click', async ({ page }) => {
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

    // Staged, not sent; the Send button names the file.
    const staged = await page.evaluate(() => {
      const btn = document.getElementById('panel').shadowRoot.getElementById('wall-picker-send-btn');
      return { enabled: !btn.disabled, label: btn.textContent };
    });
    expect(staged.enabled).toBe(true);
    expect(staged.label).toContain('photo.png');
    expect(mockServer.rawSends).toEqual([]);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-picker-send-btn').click();
    });
    await expect.poll(() => mockServer.rawSends)
      .toEqual([{ entity_id: 'sensor.entry_1_battery', has_image: true }]);

    const pickerDisplay = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display
    );
    expect(pickerDisplay).toBe('none');
  });
});
