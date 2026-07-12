const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// xOTD ("Daily Content"): many independent (content_mode, frame, schedule)
// instances managed from their own tab, not the single-instance Add-ons
// install flow -- see custom_components/fraimic/xotd.py and the
// MULTI_INSTANCE_PACK_IDS filter in fraimic-panel.js. This mirrors the
// real scene_packs/index.json "xotd" catalog entry closely enough
// (content_mode + joke/quote/scripture fields) to exercise the generic
// config_schema engine the same way agenda-calendar-source.spec.js does
// for daily_agenda.
const XOTD_PACK = {
  id: 'xotd',
  name: 'xOTD (Day-of-the-Day)',
  description: 'Joke, quote, scripture, or word of the day.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/xotd/preview_cover.jpg',
  config_schema: [
    {
      name: 'content_mode', type: 'select', label: 'Content Type', default: 'quote',
      options: [
        { value: 'joke', label: 'Joke of the Day' },
        { value: 'quote', label: 'Quote of the Day' },
        { value: 'scripture', label: 'Scripture of the Day' },
        { value: 'word', label: 'Word of the Day' },
      ],
    },
    {
      name: 'joke_feed', type: 'select', label: 'Joke Feed', default: 'icanhazdadjoke',
      options: [{ value: 'icanhazdadjoke', label: 'icanhazdadjoke.com' }, { value: 'custom', label: 'Custom API URL...' }],
      show_if: { field: 'content_mode', equals: 'joke' },
    },
    {
      name: 'quote_feed', type: 'select', label: 'Quote Feed', default: 'zenquotes',
      options: [{ value: 'zenquotes', label: 'ZenQuotes' }, { value: 'custom', label: 'Custom API URL...' }],
      show_if: { field: 'content_mode', equals: 'quote' },
    },
    {
      name: 'scripture_source', type: 'select', label: 'Scripture Source', default: 'daily_api',
      options: [{ value: 'daily_api', label: 'Daily Verse of the Day' }, { value: 'custom_list', label: 'Custom list' }],
      show_if: { field: 'content_mode', equals: 'scripture' },
    },
    {
      name: 'theme', type: 'select', label: 'Visual Theme', default: 'classic',
      options: [{ value: 'classic', label: 'Classic' }, { value: 'retro_atomic', label: 'Retro Atomic Age' }],
    },
    {
      name: 'drop_cap', type: 'boolean', label: 'Drop Cap', default: false,
    },
  ],
};

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
    return grid && grid.children.length > 0;
  });
}

async function openAddonsTab(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

async function openNewInstanceModal(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.getElementById('xotd-new-btn').click();
  });
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

// Find the xotd instance card whose title contains `titleSubstring`, then
// click a button inside it matching `buttonText`.
async function clickCardButton(page, titleSubstring, buttonText) {
  await page.evaluate(({ titleSubstring, buttonText }) => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.getElementById('xotd-grid').querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.includes(titleSubstring));
    const btn = [...card.querySelectorAll('button')].find((b) => b.textContent.includes(buttonText));
    btn.click();
  }, { titleSubstring, buttonText });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

function fieldDisplay(page, id) {
  return page.evaluate((elId) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    return el ? el.style.display : null;
  }, id);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

test.describe('xOTD "Daily Content" tab', () => {
  test('the xotd catalog pack never appears as an installable Add-on card', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openAddonsTab(page);
      await page.waitForFunction(() => {
        const root = document.getElementById('panel').shadowRoot;
        return root.getElementById('pack-grid').children.length > 0;
      });
      const hasXotdCard = await page.evaluate(() => {
        const root = document.getElementById('panel').shadowRoot;
        return [...root.querySelectorAll('.scene-card-title')].some((el) => el.textContent.includes('xOTD'));
      });
      expect(hasXotdCard).toBe(false);
    } finally {
      await mock.stop();
    }
  });

  test('creating two instances keeps them independent (different modes, frames, schedules)', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      // First instance: Joke -> Frame A, hourly.
      await openNewInstanceModal(page);
      await setFieldValue(page, 'xotd-field-content_mode', 'joke');
      await setFieldValue(page, 'xotd-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.xotdInstances.length).toBe(1);

      // Second instance: Scripture -> Frame B, daily at 08:00:00.
      await openNewInstanceModal(page);
      await setFieldValue(page, 'xotd-field-content_mode', 'scripture');
      await setFieldValue(page, 'xotd-frame', 'entry_2');
      await setFieldValue(page, 'xotd-schedule-type', 'daily');
      await setFieldValue(page, 'xotd-schedule-time', '08:00:00');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.xotdInstances.length).toBe(2);

      const [first, second] = mock.xotdInstances;
      expect(first.content_mode).toBe('joke');
      expect(first.frame_id).toBe('entry_1');
      expect(first.schedule.type).toBe('hourly');
      expect(second.content_mode).toBe('scripture');
      expect(second.frame_id).toBe('entry_2');
      expect(second.schedule).toEqual({ type: 'daily', time: '08:00:00' });

      // Both cards render simultaneously.
      const titles = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent));
      expect(titles.some((t) => t.includes('Joke') && t.includes('Living Room Frame'))).toBe(true);
      expect(titles.some((t) => t.includes('Scripture') && t.includes('Office Frame'))).toBe(true);
    } finally {
      await mock.stop();
    }
  });

  test('editing one instance\'s schedule does not affect the other', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdInstances: [
        { instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } },
        { instance_id: 'xotd_2', content_mode: 'scripture', frame_id: 'entry_2', schedule: { type: 'hourly' } },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      await clickCardButton(page, 'Joke', 'Edit');
      await page.waitForFunction(() => {
        const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
        return overlay && overlay.style.display === 'flex';
      });
      expect(await fieldValue(page, 'xotd-schedule-type')).toBe('hourly');

      await setFieldValue(page, 'xotd-schedule-type', 'daily');
      await setFieldValue(page, 'xotd-schedule-time', '09:30:00');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      await expect.poll(() => mock.xotdInstances.find((i) => i.instance_id === 'xotd_1').schedule.type).toBe('daily');
      const edited = mock.xotdInstances.find((i) => i.instance_id === 'xotd_1');
      const untouched = mock.xotdInstances.find((i) => i.instance_id === 'xotd_2');
      expect(edited.schedule).toEqual({ type: 'daily', time: '09:30:00' });
      expect(untouched.schedule).toEqual({ type: 'hourly' });
      expect(untouched.frame_id).toBe('entry_2');
    } finally {
      await mock.stop();
    }
  });

  test('deleting one instance leaves the other running', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdInstances: [
        { instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } },
        { instance_id: 'xotd_2', content_mode: 'scripture', frame_id: 'entry_2', schedule: { type: 'hourly' } },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      page.once('dialog', (dialog) => dialog.accept());
      await clickCardButton(page, 'Joke', 'Delete');

      await expect.poll(() => mock.xotdInstances.length).toBe(1);
      expect(mock.xotdInstances[0].instance_id).toBe('xotd_2');

      const titles = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent));
      expect(titles.some((t) => t.includes('Scripture'))).toBe(true);
      expect(titles.some((t) => t.includes('Joke'))).toBe(false);
    } finally {
      await mock.stop();
    }
  });

  test('image_album mode\'s album dropdown populates from the library', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      albums: [{ name: 'Vacation', count: 3, cover_image_id: null }, { name: 'Family', count: 5, cover_image_id: null }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await openNewInstanceModal(page);

      await setFieldValue(page, 'xotd-field-content_mode', 'image');
      await setFieldValue(page, 'xotd-field-sub_mode', 'image_album');

      const albumOptions = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.getElementById('xotd-field-album').querySelectorAll('option'),
      ].map((o) => o.value));
      expect(albumOptions).toContain('Vacation');
      expect(albumOptions).toContain('Family');
    } finally {
      await mock.stop();
    }
  });

  test('content_mode switching shows/hides the right field groups', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK], albums: [{ name: 'Vacation', count: 1 }] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await openNewInstanceModal(page);

      await setFieldValue(page, 'xotd-field-content_mode', 'joke');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('block');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-sub_mode')).toBe('none');

      await setFieldValue(page, 'xotd-field-content_mode', 'quote');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('block');

      await setFieldValue(page, 'xotd-field-content_mode', 'image');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-sub_mode')).toBe('block');
      // sub_mode defaults to image_feed -- feed_provider shows, album doesn't.
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('block');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('none');

      await setFieldValue(page, 'xotd-field-sub_mode', 'image_album');
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('block');

      await setFieldValue(page, 'xotd-field-sub_mode', 'image_feed');
      await setFieldValue(page, 'xotd-field-feed_provider', 'nasa_apod');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('block');
      await setFieldValue(page, 'xotd-field-feed_provider', 'wikimedia_potd');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('submit is rejected with no target frame selected', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await openNewInstanceModal(page);

      await setFieldValue(page, 'xotd-frame', '');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('select a target frame');
      expect(mock.xotdInstances.length).toBe(0);
    } finally {
      await mock.stop();
    }
  });
});
