const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton, getFeedback } = require('./fixtures/panel-page');

// Compose message: a fixed-shape modal (text + style + target-type toggle
// + save-to-library checkbox) reached from the Live tab, distinct from the
// schema-driven _openXotdModal engine -- a message is always ephemeral
// (never a persisted Skill), so there's no content-mode picker or catalog
// schema involved here, just the three fixed styles the backend renderer
// supports (plain/ad_50s/movie_poster).

function frames() {
  return [
    { entry_id: 'entry_1', title: 'Living Room Frame' },
    { entry_id: 'entry_2', title: 'Office Frame' },
  ];
}

async function openXotdTab(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="xotd"]').click();
  });
  await page.waitForFunction(() => {
    const grid = document.getElementById('panel').shadowRoot.getElementById('xotd-grid');
    return grid && grid.children.length >= 0 && document.getElementById('panel')._loaded;
  });
}

async function openComposeModal(page) {
  await openXotdTab(page);
  await clickPanelButton(page, 'compose-message-btn');
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('message-modal-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

function targetRowDisplay(page, rowId) {
  return page.evaluate((id) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(id);
    return el ? el.style.display : null;
  }, rowId);
}

async function setSelectValue(page, id, value) {
  await page.evaluate(({ id, value }) => {
    const root = document.getElementById('panel').shadowRoot;
    const sel = root.getElementById(id);
    sel.value = value;
    sel.dispatchEvent(new Event('change'));
  }, { id, value });
}

async function setTextValue(page, id, value) {
  await page.evaluate(({ id, value }) => {
    document.getElementById('panel').shadowRoot.getElementById(id).value = value;
  }, { id, value });
}

async function setChecked(page, id, checked) {
  await page.evaluate(({ id, checked }) => {
    document.getElementById('panel').shadowRoot.getElementById(id).checked = checked;
  }, { id, checked });
}

test.describe('Compose message', () => {
  test('opens with plain style and frame target selected by default', async ({ page }) => {
    const mock = createMockServer({ frames: frames() });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      expect(await page.evaluate(() =>
        document.getElementById('panel').shadowRoot.getElementById('message-style-select').value
      )).toBe('plain');
      expect(await page.evaluate(() =>
        document.getElementById('panel').shadowRoot.getElementById('message-target-type-select').value
      )).toBe('frame');
      expect(await targetRowDisplay(page, 'message-target-frame-row')).not.toBe('none');
      expect(await targetRowDisplay(page, 'message-target-scene-row')).toBe('none');
      expect(await targetRowDisplay(page, 'message-target-wall-row')).toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('all three styles are selectable', async ({ page }) => {
    const mock = createMockServer({ frames: frames() });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      const options = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot
          .getElementById('message-style-select').options,
      ].map((o) => o.value));
      expect(options).toEqual(['plain', 'ad_50s', 'movie_poster']);
    } finally {
      await mock.stop();
    }
  });

  test('target-type toggle switches the visible picker', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenes: [{ scene_id: 'scene_1', name: 'Movie Night', mappings: { entry_1: 'img_1' } }],
      walls: [{ wall_id: 'wall_1', name: 'Living Room Wall', placements: { entry_1: { x: 0, y: 0 } } }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await setSelectValue(page, 'message-target-type-select', 'scene');
      expect(await targetRowDisplay(page, 'message-target-scene-row')).not.toBe('none');
      expect(await targetRowDisplay(page, 'message-target-frame-row')).toBe('none');

      await setSelectValue(page, 'message-target-type-select', 'wall');
      expect(await targetRowDisplay(page, 'message-target-wall-row')).not.toBe('none');
      expect(await targetRowDisplay(page, 'message-target-scene-row')).toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('save-to-library is disabled and hinted for a scene target', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenes: [{ scene_id: 'scene_1', name: 'Movie Night', mappings: { entry_1: 'img_1' } }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await setSelectValue(page, 'message-target-type-select', 'scene');
      const disabled = await page.evaluate(() =>
        document.getElementById('panel').shadowRoot.getElementById('message-save-to-library-checkbox').disabled
      );
      expect(disabled).toBe(true);
      expect(await targetRowDisplay(page, 'message-save-to-library-hint')).toBe('block');

      await setSelectValue(page, 'message-target-type-select', 'frame');
      const stillDisabled = await page.evaluate(() =>
        document.getElementById('panel').shadowRoot.getElementById('message-save-to-library-checkbox').disabled
      );
      expect(stillDisabled).toBe(false);
    } finally {
      await mock.stop();
    }
  });

  test('sending to a single frame posts the right body', async ({ page }) => {
    const mock = createMockServer({ frames: frames() });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await setTextValue(page, 'message-text-input', 'Happy Birthday!');
      await setSelectValue(page, 'message-style-select', 'ad_50s');
      await setSelectValue(page, 'message-target-frame-select', 'entry_2');
      await clickPanelButton(page, 'message-modal-submit');

      await expect.poll(() => mock.messageSendCalls.length).toBe(1);
      const call = mock.messageSendCalls[0];
      expect(call.message_text).toBe('Happy Birthday!');
      expect(call.style).toBe('ad_50s');
      expect(call.target).toEqual({ type: 'frame', entry_id: 'entry_2' });
      expect(call.save_to_library).toBe(false);

      const fb = await getFeedback(page, 'message-modal-fb');
      expect(fb.className).toContain('ok');
    } finally {
      await mock.stop();
    }
  });

  test('sending to a wall with save-to-library checked posts save_to_library true', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      walls: [{ wall_id: 'wall_1', name: 'Living Room Wall', placements: { entry_1: { x: 0, y: 0 }, entry_2: { x: 1200, y: 0 } } }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await setTextValue(page, 'message-text-input', 'Movie night!');
      await setSelectValue(page, 'message-target-type-select', 'wall');
      await setSelectValue(page, 'message-target-wall-select', 'wall_1');
      await setChecked(page, 'message-save-to-library-checkbox', true);
      await clickPanelButton(page, 'message-modal-submit');

      await expect.poll(() => mock.messageSendCalls.length).toBe(1);
      const call = mock.messageSendCalls[0];
      expect(call.target).toEqual({ type: 'wall', wall_id: 'wall_1' });
      expect(call.save_to_library).toBe(true);
    } finally {
      await mock.stop();
    }
  });

  test('empty message text is rejected client-side without a network call', async ({ page }) => {
    const mock = createMockServer({ frames: frames() });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await clickPanelButton(page, 'message-modal-submit');

      const fb = await getFeedback(page, 'message-modal-fb');
      expect(fb.className).toContain('err');
      expect(mock.messageSendCalls.length).toBe(0);
    } finally {
      await mock.stop();
    }
  });

  test('a backend failure surfaces in the feedback div', async ({ page }) => {
    const mock = createMockServer({ frames: frames() });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openComposeModal(page);

      await setTextValue(page, 'message-text-input', 'Hi');
      mock.setFailing(true);
      await clickPanelButton(page, 'message-modal-submit');

      const fb = await getFeedback(page, 'message-modal-fb');
      expect(fb.className).toContain('err');
      expect(fb.text).toContain('Send failed');
    } finally {
      await mock.stop();
    }
  });
});
