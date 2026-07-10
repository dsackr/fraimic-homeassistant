const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// Auditing the generic config_schema engine turned up three more add-on
// features that were documented/coded but unreachable from the install UI --
// the same class of bug as the Daily Agenda calendar picker, just smaller:
//   - Quote of the Day's "custom" feed only ever exposed a Custom API URL
//     field; the renderer's custom_quotes local-list fallback had no field.
//   - Scripture of the Day's "custom_list" source was a no-op: nothing wrote
//     custom_scriptures into config.json, so it silently used the daily API
//     regardless of the picked source.
//   - Daily Agenda's temp_unit (F/C) was documented in config.example.json
//     but never assembled into the installed weather block.
// This covers the new 'json' field type (a validated free-text textarea
// parsed server-side into real config.json structure) plus the weather
// group now folding in more than just zip_code.

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
        { value: 'custom', label: 'Custom API URL...' },
      ],
    },
    {
      name: 'quote_api_url', type: 'string', label: 'Custom Quote API URL', required: false,
      show_if: { field: 'quote_feed', equals: 'custom' },
    },
    {
      name: 'custom_quotes', type: 'json', label: 'Custom Quotes List', required: false,
      placeholder: '[{"q": "Quote text", "a": "Author"}]',
      show_if: { field: 'quote_feed', equals: 'custom' },
    },
  ],
};

const DAILY_AGENDA_PACK = {
  id: 'daily_agenda',
  name: 'Daily Agenda',
  description: 'Calendar and weather widget.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/daily_agenda/preview_cover.jpg',
  config_schema: [
    {
      name: 'calendar_source', type: 'select', label: 'Calendar Source', default: 'ha',
      options: [
        { value: 'ha', label: 'Home Assistant Calendar' },
        { value: 'ical', label: 'Google Calendar / iCal URL' },
      ],
    },
    { name: 'ha_calendar_entity', type: 'entity', domain: 'calendar', label: 'Home Assistant Calendar', required: false, show_if: { field: 'calendar_source', equals: 'ha' } },
    { name: 'calendar_url', type: 'string', label: 'Calendar iCal URL', required: true, show_if: { field: 'calendar_source', equals: 'ical' } },
    { name: 'zip_code', type: 'string', label: 'ZIP Code or City Name', required: false, group: 'weather' },
    {
      name: 'temp_unit', type: 'select', label: 'Temperature Unit', default: 'fahrenheit', group: 'weather',
      options: [
        { value: 'fahrenheit', label: 'Fahrenheit (°F)' },
        { value: 'celsius', label: 'Celsius (°C)' },
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

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

function rowDisplay(page, name) {
  return page.evaluate((n) => document.getElementById('panel').shadowRoot.getElementById(`widget-row-${n}`).style.display, name);
}

test.describe('Add-on config_schema gap fixes', () => {
  test('Quote of the Day: custom_quotes textarea is a real JSON field, validated on submit', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [QUOTE_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await openAddons(page);
      await openModalFor(page, 'Quote of the Day');

      expect(await rowDisplay(page, 'custom_quotes')).toBe('none');
      await setFieldValue(page, 'widget-field-quote_feed', 'custom');
      expect(await rowDisplay(page, 'custom_quotes')).toBe('block');

      // A textarea, not a plain input -- confirms the 'json' field type rendered.
      const tag = await page.evaluate(() =>
        document.getElementById('panel').shadowRoot.getElementById('widget-field-custom_quotes').tagName);
      expect(tag).toBe('TEXTAREA');

      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await setFieldValue(page, 'widget-field-custom_quotes', 'not valid json{{');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('widget-config-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('must be valid JSON');
      expect(mock.installCalls.length).toBe(0);

      const quotesJson = JSON.stringify([{ q: 'Stay hungry, stay foolish.', a: 'Steve Jobs' }]);
      await setFieldValue(page, 'widget-field-custom_quotes', quotesJson);
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.custom_quotes).toBe(quotesJson);
    } finally {
      await mock.stop();
    }
  });

  test('Daily Agenda: temp_unit rides along in the weather group', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [DAILY_AGENDA_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await page.evaluate(() => {
        document.getElementById('panel')._hass.states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
      });
      await openAddons(page);
      await openModalFor(page, 'Daily Agenda');

      await setFieldValue(page, 'widget-field-temp_unit', 'celsius');
      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.temp_unit).toBe('celsius');
    } finally {
      await mock.stop();
    }
  });
});
