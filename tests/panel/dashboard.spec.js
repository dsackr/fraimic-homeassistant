// Coverage for the consolidated dashboard: Dashboard is the default tab and
// hosts the wall canvas (alongside Add-ons and Daily Content, both always
// visible), the header's Manage Library and Settings modals, tile footers
// (name + live status), send-on-pick, and the per-tile "Upload a photo" raw-
// send path.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickTile, pickImageInWallPicker } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto', last_image_id: 'image_2' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 1200, height: 1600, orientation: 'auto', last_image_id: 'image_1' },
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

  test('Dashboard is the default content tab, alongside Add-ons and Daily Content', async ({ page }) => {
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const xotdBtn = root.querySelector('.tab-btn[data-tab="xotd"]');
      return {
        tabs: [...root.querySelectorAll('.tab-btn')].map((b) => b.dataset.tab),
        activeContent: root.getElementById('tab-dashboard').classList.contains('active'),
        headerButtons: ['frame-add-btn', 'library-open-btn', 'settings-open-btn']
          .map((id) => !!root.getElementById(id)),
        // Daily Content (skills) has no install gate -- always visible,
        // unlike the retired per-instance xOTD model's hidden-until-
        // installed tab button.
        xotdTabHidden: xotdBtn.style.display === 'none',
      };
    });
    expect(state.tabs).toEqual(['dashboard', 'addons', 'xotd']);
    expect(state.activeContent).toBe(true);
    expect(state.headerButtons).toEqual([true, true, true]);
    expect(state.xotdTabHidden).toBe(false);
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

  test('viewing shows on-frame content; modeling blanks every unassigned tile', async ({ page }) => {
    const readTiles = () => page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const out = {};
      for (const tile of root.querySelectorAll('.wall-tile')) {
        const badge = tile.querySelector('.wall-tile-badge');
        const media = tile.querySelector('.wall-tile-media');
        out[tile.dataset.entryId] = {
          badge: badge && badge.style.display !== 'none' ? badge.dataset.kind : null,
          blank: !media.querySelector('img') && !media.querySelector('.thumb-img, canvas')
            && media.textContent.trim().length > 0,
        };
      }
      return out;
    });

    // VIEWING mode (nothing staged, no scene): every tile shows what's on
    // its physical frame, labeled.
    let tiles = await readTiles();
    expect(tiles.entry_1.badge).toBe('onframe');
    expect(tiles.entry_2.badge).toBe('onframe');

    // Selecting a scene enters MODELING mode: the mapped tile carries the
    // scene image ("scene" badge); the unmapped one goes BLANK -- blank
    // means Send to Frames will not touch it.
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const sel = root.getElementById('wall-scene-select');
      sel.value = 'scene_1';
      sel.dispatchEvent(new Event('change'));
    });
    tiles = await readTiles();
    expect(tiles.entry_1.badge).toBe('scene');
    expect(tiles.entry_2.badge).toBe(null);
    expect(tiles.entry_2.blank).toBe(true);

    // A pick this session upgrades that tile's badge to "staged".
    await clickTile(page, 'entry_1');
    await pickImageInWallPicker(page, 'image_2');
    tiles = await readTiles();
    expect(tiles.entry_1.badge).toBe('staged');

    // Clear All empties the model: every tile blank, nothing sent.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-clear-all-btn').click();
    });
    tiles = await readTiles();
    expect(tiles.entry_1.badge).toBe(null);
    expect(tiles.entry_1.blank).toBe(true);
    expect(tiles.entry_2.blank).toBe(true);
    expect(await page.evaluate(() => document.getElementById('panel')._wallPendingMappings))
      .toEqual({ entry_1: '', entry_2: '' });
    expect(mockServer.sends).toEqual([]);
    expect(mockServer.rawSends).toEqual([]);
  });

  test('clicking an image stages it and closes the picker -- the Send button is the transmit moment', async ({ page }) => {
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

    // Staged (pending mapping) and dismissed, NOT sent.
    const staged = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const root = panel.shadowRoot;
      return {
        pending: panel._wallPendingMappings,
        pickerDisplay: root.getElementById('wall-image-picker-overlay').style.display,
      };
    });
    expect(staged.pending).toEqual({ entry_1: 'image_1' });
    expect(staged.pickerDisplay).toBe('none');
    expect(mockServer.sends).toEqual([]);

    // Reopening the picker shows the staged pick already selected, with
    // the Send button armed to transmit it.
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot
        .querySelectorAll('#wall-image-picker-grid .image-picker-cell.selected').length === 1
    );
    const reopened = await page.evaluate(() => {
      const btn = document.getElementById('panel').shadowRoot.getElementById('wall-picker-send-btn');
      return { sendEnabled: !btn.disabled, sendLabel: btn.textContent };
    });
    expect(reopened.sendEnabled).toBe(true);
    expect(reopened.sendLabel).toContain('Living Room Frame');
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
