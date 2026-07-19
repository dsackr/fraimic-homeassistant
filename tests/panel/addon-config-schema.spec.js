const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// _openWidgetConfigModal used to have one hardcoded HTML branch per known
// field name (quote_feed, bible_translation, scripture_source, ...) baked
// into digital-frames-panel.js. It's now a generic renderer driven entirely by
// each pack's config_schema (type: select/entity/string, show_if, default,
// group) -- see _renderConfigField. This covers the two other widget packs
// that relied on the old hardcoded branches, proving the generic engine
// reproduces their behavior with no per-pack panel code left.
const QUOTE_PACK = {
  id: 'quote_of_the_day',
  name: 'Quote of the Day',
  description: 'Quote widget.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/quote_of_the_day/preview_cover.jpg',
  config_schema: [
    {
      name: 'quote_feed', type: 'select', label: 'Quote Feed', default: 'zenquotes',
      options: [
        { value: 'zenquotes', label: 'ZenQuotes (Inspirational)' },
        { value: 'favqs', label: 'FavQs (General)' },
        { value: 'custom', label: 'Custom API URL...' },
      ],
    },
    {
      name: 'quote_api_url', type: 'string', label: 'Custom Quote API URL', required: true,
      placeholder: 'https://...', show_if: { field: 'quote_feed', equals: 'custom' },
    },
  ],
};

const SCRIPTURE_PACK = {
  id: 'scripture_of_the_day',
  name: 'Scripture of the Day',
  description: 'Scripture widget.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/scripture_of_the_day/preview_cover.jpg',
  config_schema: [
    {
      name: 'bible_translation', type: 'select', label: 'Bible Translation', default: 'niv',
      options: [
        { value: 'niv', label: 'NIV (New International Version)' },
        { value: 'kjv', label: 'KJV (King James Version)' },
      ],
    },
    {
      name: 'scripture_source', type: 'select', label: 'Scripture Source', default: 'daily_api',
      options: [
        { value: 'daily_api', label: 'Daily Verse of the Day' },
        { value: 'custom_list', label: 'Custom list configured in JSON' },
      ],
    },
  ],
};

async function openAddons(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

async function openModalFor(page, packName) {
  await page.evaluate((name) => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.trim() === name);
    card.querySelector('.pack-cover').click();
  }, packName);
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('widget-config-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

function rowDisplay(page, name) {
  return page.evaluate((n) => document.getElementById('panel').shadowRoot.getElementById(`widget-row-${n}`).style.display, name);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

test.describe('Generic add-on config_schema engine', () => {
  test('Quote of the Day: select defaults, custom URL row hidden until "Custom" is picked and required only then', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [QUOTE_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await openAddons(page);
      await openModalFor(page, 'Quote of the Day');

      expect(await fieldValue(page, 'widget-field-quote_feed')).toBe('zenquotes');
      expect(await rowDisplay(page, 'quote_api_url')).toBe('none');

      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.quote_feed).toBe('zenquotes');

      // Reopen, switch to Custom -- the URL row appears and is now required.
      await openModalFor(page, 'Quote of the Day');
      await setFieldValue(page, 'widget-field-quote_feed', 'custom');
      expect(await rowDisplay(page, 'quote_api_url')).toBe('block');

      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('widget-config-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('Custom Quote API URL is required');
      expect(mock.installCalls.length).toBe(1); // still just the first, rejected client-side

      await setFieldValue(page, 'widget-field-quote_api_url', 'https://example.com/quotes.json');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(2);
      expect(mock.installCalls[1].config.quote_feed).toBe('custom');
      expect(mock.installCalls[1].config.quote_api_url).toBe('https://example.com/quotes.json');
    } finally {
      await mock.stop();
    }
  });

  test('Scripture of the Day: two independent selects with no conditional rows install cleanly', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [SCRIPTURE_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await openAddons(page);
      await openModalFor(page, 'Scripture of the Day');

      expect(await fieldValue(page, 'widget-field-bible_translation')).toBe('niv');
      expect(await fieldValue(page, 'widget-field-scripture_source')).toBe('daily_api');

      await setFieldValue(page, 'widget-field-bible_translation', 'kjv');
      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.bible_translation).toBe('kjv');
      expect(mock.installCalls[0].config.scripture_source).toBe('daily_api');
    } finally {
      await mock.stop();
    }
  });
});
