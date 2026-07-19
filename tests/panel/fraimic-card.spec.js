// The Fraimic Lovelace card: frame-based (not entity-based) config, latest
// on-frame image (library sends AND upload/xOTD render previews), and
// manage-the-frame actions (upload, library pick, daily skills, orientation,
// crop) at parity with the sidebar panel's wall view.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');

const FRAMES = [
  {
    entry_id: 'entry_1', title: 'Living Room Frame', size: '13.3',
    width: 1200, height: 1600, orientation: 'portrait',
    battery_entity_id: 'sensor.entry_1_battery',
    orientation_entity_id: 'select.entry_1_orientation',
    online: true, last_image_id: null, has_thumbnail: false, queued: false,
  },
  {
    entry_id: 'entry_2', title: 'Kitchen Frame', size: '7.3',
    width: 800, height: 480, orientation: 'auto',
    battery_entity_id: 'sensor.entry_2_battery',
    orientation_entity_id: 'select.entry_2_orientation',
    online: true, last_image_id: null, has_thumbnail: false, queued: false,
  },
];
const IMAGES = [
  { image_id: 'image_beach', filename: 'beach.png', albums: ['Vacation'] },
  { image_id: 'image_dog', filename: 'dog.png', albums: [] },
];
const ALBUMS = [{ name: 'Vacation', count: 1, cover_image_id: 'image_beach' }];
const SKILLS = [{ skill_id: 'skill_word', name: 'Word of the Day', content_mode: 'word', config: {} }];

function cardQ(page, id) {
  return page.evaluate((elId) => {
    const el = document.getElementById('card').shadowRoot.getElementById(elId);
    if (!el) return null;
    return {
      display: el.style.display,
      text: el.textContent,
      disabled: !!el.disabled,
      className: el.className,
    };
  }, id);
}

async function mountCard(page, baseUrl, config, frames) {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err));
  await page.goto(`${baseUrl}/card-harness.html`);
  await page.evaluate(
    ({ config, frames }) => window.__mountCard(config, frames),
    { config, frames }
  );
  return pageErrors;
}

test.describe('Fraimic card', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    if (mockServer) await mockServer.stop();
    mockServer = null;
  });

  async function start(opts) {
    mockServer = createMockServer(opts);
    baseUrl = await mockServer.start();
  }

  test('editor lists frames by name and writes an entry_id config', async ({ page }) => {
    await start({ frames: FRAMES });
    await page.goto(`${baseUrl}/card-harness.html`);
    await page.evaluate((frames) => window.__mountEditor({}, frames), FRAMES);

    await page.waitForFunction(() => {
      const sel = document.getElementById('editor').shadowRoot.getElementById('frame');
      return sel && sel.options.length >= 2;
    });
    const labels = await page.evaluate(() =>
      [...document.getElementById('editor').shadowRoot.getElementById('frame').options]
        .filter((o) => o.value)
        .map((o) => o.textContent)
    );
    expect(labels).toEqual(['Living Room Frame (13.3")', 'Kitchen Frame (7.3")']);

    await page.evaluate(() => {
      const sel = document.getElementById('editor').shadowRoot.getElementById('frame');
      sel.value = 'entry_2';
      sel.dispatchEvent(new Event('change'));
    });
    const configs = await page.evaluate(() => window.__editorConfigs);
    expect(configs[configs.length - 1].entry_id).toBe('entry_2');
  });

  test('editor resolves a legacy entity config to its frame', async ({ page }) => {
    await start({ frames: FRAMES });
    await page.goto(`${baseUrl}/card-harness.html`);
    await page.evaluate(
      (frames) => window.__mountEditor({ entity: 'sensor.entry_2_battery' }, frames),
      FRAMES
    );
    await page.waitForFunction(() => {
      const sel = document.getElementById('editor').shadowRoot.getElementById('frame');
      return sel && sel.value === 'entry_2';
    });
  });

  test('shows the frame name, battery status, and the last library image with an ON FRAME badge', async ({ page }) => {
    const frames = [{ ...FRAMES[0], last_image_id: 'image_beach' }, FRAMES[1]];
    await start({ frames, images: IMAGES });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, frames);

    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('mediaImg').style.display === 'block'
    );
    expect((await cardQ(page, 'frameName')).text).toBe('Living Room Frame');
    expect((await cardQ(page, 'frameStatus')).text).toContain('90%');
    const badge = await cardQ(page, 'badge');
    expect(badge.display).toBe('block');
    expect(badge.text).toBe('ON FRAME');
    expect(mockServer.requestLog).toContain('GET /api/digital_frames/library/image/image_beach?thumb=480');
  });

  test('a render-preview send (upload or xOTD skill) shows via the frame thumbnail endpoint', async ({ page }) => {
    const frames = [{ ...FRAMES[0], last_image_id: null, has_thumbnail: true }, FRAMES[1]];
    await start({ frames });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, frames);

    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('mediaImg').style.display === 'block'
    );
    expect(mockServer.requestLog).toContain('GET /api/digital_frames/frame/entry_1/thumbnail');
    // Render previews are shown whole (contain), not cropped like photos.
    const cls = await page.evaluate(
      () => document.getElementById('card').shadowRoot.getElementById('mediaImg').className
    );
    expect(cls).toContain('render');
  });

  test('legacy entity config still resolves and renders the frame', async ({ page }) => {
    await start({ frames: FRAMES });
    await mountCard(page, baseUrl, { entity: 'sensor.entry_1_battery' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('frameName').textContent === 'Living Room Frame'
    );
  });

  test('picking a library photo stages it, and Send posts to library/send', async ({ page }) => {
    await start({ frames: FRAMES, images: IMAGES, albums: ALBUMS });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('frameName').textContent === 'Living Room Frame'
    );

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnPhotos').click());
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.querySelectorAll('#pickerGrid .picker-cell').length === 2
    );
    await page.evaluate(() => {
      document.getElementById('card').shadowRoot.querySelector('#pickerGrid .picker-cell').click();
    });

    // Staged: actions row visible, PREVIEW badge up, nothing sent yet.
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('actions').style.display === 'flex'
    );
    expect((await cardQ(page, 'badge')).text).toBe('PREVIEW');
    expect(mockServer.sends).toEqual([]);

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnSend').click());
    await page.waitForFunction(() =>
      document.getElementById('card').shadowRoot.getElementById('feedback').textContent.includes('Sent')
    );
    expect(mockServer.sends).toEqual([
      { entity_id: 'sensor.entry_1_battery', image_id: 'image_beach', packer: undefined },
    ]);
  });

  test('uploading a photo stages it, and Send posts multipart to send_image', async ({ page }) => {
    await start({ frames: FRAMES });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('frameName').textContent === 'Living Room Frame'
    );

    await page.setInputFiles('#card input[type="file"]', {
      name: 'holiday.png',
      mimeType: 'image/png',
      buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    });

    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('actions').style.display === 'flex'
    );
    expect((await cardQ(page, 'badge')).text).toBe('PREVIEW');
    expect(mockServer.rawSends).toEqual([]);

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnSend').click());
    await page.waitForFunction(() =>
      document.getElementById('card').shadowRoot.getElementById('feedback').textContent.includes('Sent')
    );
    expect(mockServer.rawSends).toEqual([
      { entity_id: 'sensor.entry_1_battery', has_image: true },
    ]);
  });

  test('picking a daily skill and sending posts to skills/:id/send with the entry_id', async ({ page }) => {
    await start({ frames: FRAMES, skills: SKILLS });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('frameName').textContent === 'Living Room Frame'
    );

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnDaily').click());
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.querySelectorAll('#pickerGrid .picker-cell').length === 1
    );
    await page.evaluate(() => {
      document.getElementById('card').shadowRoot.querySelector('#pickerGrid .picker-cell').click();
    });
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('actions').style.display === 'flex'
    );
    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnSend').click());
    await page.waitForFunction(() =>
      document.getElementById('card').shadowRoot.getElementById('feedback').textContent.includes('Sent')
    );
    expect(mockServer.skillSendCalls).toEqual([{ skill_id: 'skill_word', entry_id: 'entry_1' }]);
  });

  test('orientation buttons call select.select_option on the frame\'s orientation entity', async ({ page }) => {
    await start({ frames: FRAMES });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('orientLandscape').style.display !== 'none'
    );

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('orientLandscape').click());
    await page.waitForFunction(() => (window.__serviceCalls || []).length === 1);
    const calls = await page.evaluate(() => window.__serviceCalls);
    expect(calls).toEqual([{
      domain: 'select',
      service: 'select_option',
      data: { entity_id: 'select.entry_1_orientation', option: 'Landscape' },
    }]);
  });

  test('crop is disabled without a library image, enabled with one, and Save & Send saves the crop then re-sends', async ({ page }) => {
    // No library image on the frame -> disabled.
    await start({ frames: FRAMES, images: IMAGES });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, FRAMES);
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('frameName').textContent === 'Living Room Frame'
    );
    expect((await cardQ(page, 'btnCrop')).disabled).toBe(true);
    await mockServer.stop();

    // Library image on the frame -> enabled; the full crop flow works.
    const frames = [{ ...FRAMES[0], last_image_id: 'image_beach' }, FRAMES[1]];
    await start({ frames, images: IMAGES });
    await mountCard(page, baseUrl, { entry_id: 'entry_1' }, frames);
    await page.waitForFunction(
      () => !document.getElementById('card').shadowRoot.getElementById('btnCrop').disabled
    );

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('btnCrop').click());
    await page.waitForFunction(
      () => document.getElementById('card').shadowRoot.getElementById('cropBox').style.display === 'block'
    );

    await page.evaluate(() => document.getElementById('card').shadowRoot.getElementById('cropSaveSend').click());
    await page.waitForFunction(() =>
      document.getElementById('card').shadowRoot.getElementById('cropFb').textContent.includes('sent')
    );
    expect(mockServer.cropSaves).toHaveLength(1);
    expect(mockServer.cropSaves[0].image_id).toBe('image_beach');
    expect(mockServer.cropSaves[0].width).toBe(1200);
    expect(mockServer.cropSaves[0].height).toBe(1600);
    expect(mockServer.cropSaves[0].crop_box).toHaveLength(4);
    expect(mockServer.sends).toEqual([
      { entity_id: 'sensor.entry_1_battery', image_id: 'image_beach', packer: undefined },
    ]);
  });
});
