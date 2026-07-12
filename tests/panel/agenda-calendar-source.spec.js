const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// The Daily Agenda add-on's install form used to force a Google/iCal URL as
// a required field, with no way to pick one of the calendars Home Assistant
// already knows about. Regression coverage for the fix: the calendar_url
// field is now optional, and defaults to a "Configured Calendars" picker
// backed by hass.states (any calendar.* entity -- Google Calendar, Local
// Calendar, CalDAV, etc., not specifically Google), with the iCal URL as an
// alternate mode. The picker allows selecting more than one calendar --
// ha_calendar_entities is a comma-joined list of the checked entity ids.
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
        { value: 'ha', label: 'Configured Calendars' },
        { value: 'ical', label: 'Google Calendar / iCal URL' },
      ],
    },
    {
      name: 'ha_calendar_entities', type: 'entity', domain: 'calendar', multiple: true, label: 'Configured Calendars',
      required: false, show_if: { field: 'calendar_source', equals: 'ha' },
    },
    {
      name: 'calendar_url', type: 'string', label: 'Calendar iCal URL', required: true,
      placeholder: 'https://calendar.google.com/...', show_if: { field: 'calendar_source', equals: 'ical' },
    },
    { name: 'zip_code', type: 'string', label: 'ZIP Code or City Name', required: false, placeholder: 'e.g. 90210 or London', group: 'weather' },
  ],
};

async function openAddons(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

async function openDailyAgendaModal(page) {
  await page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.trim() === 'Daily Agenda');
    card.querySelector('.pack-cover').click();
  });
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('widget-config-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

function fieldDisplay(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).style.display, id);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

// Checkbox ids in the "Configured Calendars" group, in rendered order.
function checkboxEntityIds(page, containerId) {
  return page.evaluate((id) =>
    [...document.getElementById('panel').shadowRoot.getElementById(id).querySelectorAll('input[type="checkbox"]')]
      .map((cb) => cb.value), containerId);
}

// A real .click() (not a synthetic dispatchEvent) so the native bubbling
// 'change' event reaches the container div's listener, same as a user click.
async function checkCalendarEntity(page, containerId, entityId) {
  await page.evaluate(({ id, eid }) => {
    const root = document.getElementById('panel').shadowRoot;
    const cb = [...root.getElementById(id).querySelectorAll('input[type="checkbox"]')]
      .find((el) => el.value === eid);
    cb.click();
  }, { id: containerId, eid: entityId });
}

test.describe('Daily Agenda add-on: calendar source picker', () => {
  test('defaults to the Configured Calendars picker and installs without an iCal URL', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [DAILY_AGENDA_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });

      // Seed a couple of HA calendar entities, same as a real hass object
      // would already have populated before the panel ever opens.
      await page.evaluate(() => {
        const states = document.getElementById('panel')._hass.states;
        states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
        states['calendar.work'] = { state: 'off', attributes: { friendly_name: 'Work Calendar' } };
      });

      await openAddons(page);
      await openDailyAgendaModal(page);

      expect(await fieldValue(page, 'widget-field-calendar_source')).toBe('ha');
      expect(await fieldDisplay(page, 'widget-row-ha_calendar_entities')).toBe('block');
      expect(await fieldDisplay(page, 'widget-row-calendar_url')).toBe('none');

      expect(await checkboxEntityIds(page, 'widget-field-ha_calendar_entities'))
        .toEqual(['calendar.home', 'calendar.work']);

      // Select both calendars -- the whole point of the checklist over a
      // single <select> is picking more than one.
      await checkCalendarEntity(page, 'widget-field-ha_calendar_entities', 'calendar.home');
      await checkCalendarEntity(page, 'widget-field-ha_calendar_entities', 'calendar.work');

      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });

      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.calendar_source).toBe('ha');
      expect(mock.installCalls[0].config.ha_calendar_entities).toBe('calendar.home,calendar.work');
      expect(mock.installCalls[0].config.calendar_url).toBe('');
    } finally {
      await mock.stop();
    }
  });

  test('leaving every calendar unchecked still installs (backend falls back to the first available entity)', async ({ page }) => {
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
      await openDailyAgendaModal(page);
      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });

      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.calendar_source).toBe('ha');
      expect(mock.installCalls[0].config.ha_calendar_entities).toBe('');
    } finally {
      await mock.stop();
    }
  });

  test('switching to iCal mode requires a URL and is saved/restored correctly', async ({ page }) => {
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
      await openDailyAgendaModal(page);

      await setFieldValue(page, 'widget-field-calendar_source', 'ical');
      expect(await fieldDisplay(page, 'widget-row-ha_calendar_entities')).toBe('none');
      expect(await fieldDisplay(page, 'widget-row-calendar_url')).toBe('block');

      await setFieldValue(page, 'widget-config-frame', 'entry_1');

      // Blank URL in iCal mode must be rejected client-side (no install call).
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('widget-config-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('Calendar iCal URL is required');
      expect(mock.installCalls.length).toBe(0);

      await setFieldValue(page, 'widget-field-calendar_url', 'https://calendar.google.com/private-abc/basic.ics');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.calendar_source).toBe('ical');
      expect(mock.installCalls[0].config.calendar_url).toBe('https://calendar.google.com/private-abc/basic.ics');
      // The (hidden) checklist still rides along in the payload as an empty
      // string -- the backend only reads it when calendar_source is 'ha', so
      // its presence here is harmless, not a bug.
    } finally {
      await mock.stop();
    }
  });

  test('re-editing an installed config restores the previously checked calendars', async ({ page }) => {
    // Shaped like what scene_packs.py's async_list_available actually
    // returns for an installed widget: installed: true plus the raw
    // config_data dict it was installed with (see its "installed"/"config"
    // fields, scene_packs.py).
    const installedPack = {
      ...DAILY_AGENDA_PACK,
      installed: true,
      config: {
        frame_id: 'entry_1',
        calendar_source: 'ha',
        ha_calendar_entities: 'calendar.work',
        calendar_url: '',
        zip_code: '',
        schedule: { type: 'hourly' },
      },
    };
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [installedPack],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await page.evaluate(() => {
        const states = document.getElementById('panel')._hass.states;
        states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
        states['calendar.work'] = { state: 'off', attributes: { friendly_name: 'Work Calendar' } };
      });

      await openAddons(page);
      await openDailyAgendaModal(page);

      const checkedState = await page.evaluate(() =>
        [...document.getElementById('panel').shadowRoot
          .getElementById('widget-field-ha_calendar_entities').querySelectorAll('input[type="checkbox"]')]
          .map((cb) => ({ id: cb.value, checked: cb.checked })));
      expect(checkedState).toEqual([
        { id: 'calendar.home', checked: false },
        { id: 'calendar.work', checked: true },
      ]);
    } finally {
      await mock.stop();
    }
  });

  test('"Select all" / "Clear" toolbar checks and unchecks every calendar', async ({ page }) => {
    // Generic to any entity+multiple field (see _renderConfigField in
    // fraimic-panel.js) -- exercised here through the calendar field since
    // that's the only add-on currently using this schema shape.
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [DAILY_AGENDA_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await page.evaluate(() => {
        const states = document.getElementById('panel')._hass.states;
        states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
        states['calendar.work'] = { state: 'off', attributes: { friendly_name: 'Work Calendar' } };
        states['calendar.kids'] = { state: 'off', attributes: { friendly_name: 'Kids' } };
      });

      await openAddons(page);
      await openDailyAgendaModal(page);

      const checkedValues = () => page.evaluate(() =>
        [...document.getElementById('panel').shadowRoot
          .getElementById('widget-field-ha_calendar_entities').querySelectorAll('input[type="checkbox"]:checked')]
          .map((cb) => cb.value));

      expect(await checkedValues()).toEqual([]);

      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot
          .querySelector('.entity-select-all[data-target="widget-field-ha_calendar_entities"]').click();
      });
      expect(await checkedValues()).toEqual(['calendar.home', 'calendar.kids', 'calendar.work']);

      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot
          .querySelector('.entity-clear-all[data-target="widget-field-ha_calendar_entities"]').click();
      });
      expect(await checkedValues()).toEqual([]);

      // Confirms the click also drives the submit payload, not just the
      // checkbox DOM state (dispatches 'change' same as a real user click).
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot
          .querySelector('.entity-select-all[data-target="widget-field-ha_calendar_entities"]').click();
      });
      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.ha_calendar_entities).toBe('calendar.home,calendar.kids,calendar.work');
    } finally {
      await mock.stop();
    }
  });
});
