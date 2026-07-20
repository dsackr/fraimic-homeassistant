const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// Skills ("Daily Content" tab): frame-agnostic content presets (Word/Joke/
// Quote/Scripture of the Day, or an image feed/album) -- unlike the retired
// per-instance xOTD model, a skill has no frame or schedule of its own, so
// the tab has no install gate and no Target Frame/Schedule fields. One tile
// per content type opens the New Skill modal pre-selected to that type;
// each card gets its own frame <select> + "Send Now" button since sending
// is ad hoc, not tied to a fixed frame.
//
// This mirrors the real scene_packs/index.json "xotd" catalog entry closely
// enough (content_mode + joke/quote/scripture + theme/drop_cap fields) to
// exercise the generic config_schema engine the same way
// agenda-calendar-source.spec.js does for daily_agenda.
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
    // Deliberately no show_if -- these apply "to all 4 text modes", the
    // exact case that once leaked into the image modes' fields too.
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

function xotdTabButtonDisplay(page) {
  return page.evaluate(() => {
    const btn = document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="xotd"]');
    return btn ? btn.style.display : null;
  });
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

async function clickModeTile(page, mode) {
  await page.evaluate((m) => {
    const root = document.getElementById('panel').shadowRoot;
    const tiles = [...root.querySelectorAll('.xotd-mode-tile')];
    const tile = tiles.find((t) => t.querySelector('.xotd-mode-tile-title').textContent.toLowerCase().includes(m));
    tile.click();
  }, mode);
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

// Find the skill card whose title contains `titleSubstring`, then click a
// button inside it matching `buttonText` (label text, aria-label, or title).
async function clickCardButton(page, titleSubstring, buttonText) {
  await page.evaluate(({ titleSubstring, buttonText }) => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.getElementById('xotd-grid').querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.includes(titleSubstring));
    const btn = [...card.querySelectorAll('button')].find((b) => {
      const hay = [
        b.textContent || '',
        b.getAttribute('aria-label') || '',
        b.getAttribute('title') || '',
        b.id || '',
      ].join(' ');
      return hay.includes(buttonText);
    });
    if (!btn) throw new Error(`No button matching "${buttonText}" on card "${titleSubstring}"`);
    btn.click();
  }, { titleSubstring, buttonText });
}

async function selectCardFrame(page, titleSubstring, entryId) {
  await page.evaluate(({ titleSubstring, entryId }) => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.getElementById('xotd-grid').querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.includes(titleSubstring));
    const select = card.querySelector('select');
    select.value = entryId;
    select.dispatchEvent(new Event('change'));
  }, { titleSubstring, entryId });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

// Effective visibility, not just the row's own inline style: fields with
// no show_if of their own (theme/drop_cap) are hidden by their ancestor
// wrapper (#xotd-text-fields-wrap / #xotd-image-fields-wrap) toggling,
// never by their own row's style.display -- offsetParent is null whenever
// the element or any ancestor has display:none, regardless of which one.
function fieldDisplay(page, id) {
  return page.evaluate((elId) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    if (!el) return null;
    return el.offsetParent !== null ? 'visible' : 'none';
  }, id);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

test.describe('Skills ("Daily Content" tab)', () => {
  test('the tab is always visible -- no install gate', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      expect(await xotdTabButtonDisplay(page)).not.toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('creating two skills via mode tiles keeps them independent, with no frame/schedule fields', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      // First skill: Joke.
      await clickModeTile(page, 'joke');
      expect(await fieldValue(page, 'xotd-field-content_mode')).toBe('joke');
      // No frame/schedule fields exist anymore -- a skill is frame-agnostic.
      expect(await page.evaluate(() => !!document.getElementById('panel').shadowRoot.getElementById('xotd-frame'))).toBe(false);
      expect(await page.evaluate(() => !!document.getElementById('panel').shadowRoot.getElementById('xotd-schedule-type'))).toBe(false);
      await setFieldValue(page, 'xotd-name', 'My Daily Joke');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.skills.length).toBe(1);

      // Second skill: Scripture.
      await clickModeTile(page, 'scripture');
      expect(await fieldValue(page, 'xotd-field-content_mode')).toBe('scripture');
      await setFieldValue(page, 'xotd-name', 'Morning Verse');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.skills.length).toBe(2);

      const [first, second] = mock.skills;
      expect(first.content_mode).toBe('joke');
      expect(first.name).toBe('My Daily Joke');
      expect(second.content_mode).toBe('scripture');
      expect(second.name).toBe('Morning Verse');

      // The card list re-render is a separate async chain from the mock
      // server's own state update above (fetch -> reload -> re-render), so
      // poll the DOM rather than reading it the instant the server confirms.
      await expect.poll(() => page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent))).toEqual(expect.arrayContaining(['My Daily Joke', 'Morning Verse']));
    } finally {
      await mock.stop();
    }
  });

  test('editing one skill\'s name does not affect the other', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      skills: [
        { skill_id: 'skill_1', name: 'Joke of the Day', content_mode: 'joke' },
        { skill_id: 'skill_2', name: 'Scripture of the Day', content_mode: 'scripture' },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      await clickCardButton(page, 'Joke of the Day', 'Edit');
      await page.waitForFunction(() => {
        const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
        return overlay && overlay.style.display === 'flex';
      });
      expect(await fieldValue(page, 'xotd-name')).toBe('Joke of the Day');

      await setFieldValue(page, 'xotd-name', 'Renamed Joke');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      await expect.poll(() => mock.skills.find((s) => s.skill_id === 'skill_1').name).toBe('Renamed Joke');
      const untouched = mock.skills.find((s) => s.skill_id === 'skill_2');
      expect(untouched.name).toBe('Scripture of the Day');
    } finally {
      await mock.stop();
    }
  });

  test('deleting one skill leaves the other intact', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      skills: [
        { skill_id: 'skill_1', name: 'Joke of the Day', content_mode: 'joke' },
        { skill_id: 'skill_2', name: 'Scripture of the Day', content_mode: 'scripture' },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      page.once('dialog', (dialog) => dialog.accept());
      await clickCardButton(page, 'Joke of the Day', 'Delete');

      await expect.poll(() => mock.skills.length).toBe(1);
      expect(mock.skills[0].skill_id).toBe('skill_2');

      // The card removal is async (delete -> reload -> re-render), so poll
      // the DOM rather than reading it the instant the server confirms.
      await expect.poll(() => page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent))).toEqual(expect.arrayContaining([expect.stringContaining('Scripture')]));
      const titles = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent));
      expect(titles.some((t) => t.includes('Joke'))).toBe(false);
    } finally {
      await mock.stop();
    }
  });

  test('"Send Now" sends to whichever frame is chosen in the card\'s own select', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      skills: [{ skill_id: 'skill_1', name: 'Joke of the Day', content_mode: 'joke' }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      await selectCardFrame(page, 'Joke of the Day', 'entry_2');
      await clickCardButton(page, 'Joke of the Day', 'Send Now');

      await expect.poll(() => mock.skillSendCalls).toEqual([{ skill_id: 'skill_1', entry_id: 'entry_2' }]);
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
      await clickModeTile(page, 'image album');

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
    const mock = createMockServer({
      frames: frames(), scenePacks: [XOTD_PACK], albums: [{ name: 'Vacation', count: 1 }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await clickModeTile(page, 'quote'); // any tile opens the same modal

      await setFieldValue(page, 'xotd-field-content_mode', 'joke');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      // theme/drop_cap have no show_if of their own -- they must still show
      // for every text mode via the wrapping container.
      expect(await fieldDisplay(page, 'xotd-row-theme')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-drop_cap')).toBe('visible');

      await setFieldValue(page, 'xotd-field-content_mode', 'quote');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('visible');

      await setFieldValue(page, 'xotd-field-content_mode', 'image_feed');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('none');
      // The bug this test pins: Visual Theme / Drop Cap must NOT show for
      // an image mode -- they're text-mode-only fields with no show_if of
      // their own, so without the wrapping container they'd leak through.
      expect(await fieldDisplay(page, 'xotd-row-theme')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-drop_cap')).toBe('none');

      await setFieldValue(page, 'xotd-field-feed_provider', 'nasa_apod');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('visible');
      await setFieldValue(page, 'xotd-field-feed_provider', 'wikimedia_potd');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('none');

      await setFieldValue(page, 'xotd-field-content_mode', 'image_album');
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('visible');
    } finally {
      await mock.stop();
    }
  });

  test('submit is rejected with no name given', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await clickModeTile(page, 'joke');

      await setFieldValue(page, 'xotd-name', '');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('name');
      expect(mock.skills.length).toBe(0);
    } finally {
      await mock.stop();
    }
  });
});
