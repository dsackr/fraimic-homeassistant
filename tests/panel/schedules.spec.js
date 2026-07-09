// Scheduled events: the desk calendar on the library shelf, the month-grid
// popup behind it, and the shared schedule dialog reached from all three
// entry points (popup "＋ New event", the wall's Schedule… button, the
// per-tile picker's Schedule…). Backend firing is schedules.py's job; these
// tests cover the panel's record-building (especially that the "In…" mode
// is pure sugar over a once trigger) and the popup's manage actions.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  selectWallScene,
  clickPanelButton,
  getFeedback,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_vacation', filename: 'beach.png', albums: ['Vacation'] },
  { image_id: 'image_family', filename: 'reunion.png', albums: [] },
];
const ALBUMS = [
  { name: 'Vacation', count: 1, cover_image_id: 'image_vacation' },
];
const SCENES = [
  { scene_id: 'scene_fall', name: 'Fall Colors', mappings: { entry_1: 'image_vacation' } },
];

function pad(n) { return String(n).padStart(2, '0'); }
function localDateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// A once schedule later today -- lands in the popup's initial (current)
// month and on its initially selected day.
function todayOnceSchedule() {
  return {
    schedule_id: 'schedule_seeded',
    name: 'Seeded Event',
    action: { type: 'scene', scene_id: 'scene_fall' },
    trigger: { type: 'once', at: `${localDateKey(new Date())}T23:58` },
  };
}

function panelEval(page, fn, arg) {
  return page.evaluate(fn, arg);
}

async function openCalendarPopup(page) {
  await clickPanelButton(page, 'schedule-calendar-btn');
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.getElementById('schedule-calendar-overlay').style.display === 'flex'
  );
}

async function waitForDialog(page) {
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'flex'
  );
}

async function setDialogName(page, name) {
  await panelEval(page, (value) => {
    document.getElementById('panel').shadowRoot.getElementById('schedule-name').value = value;
  }, name);
}

async function pickWhenMode(page, mode) {
  await panelEval(page, (m) => {
    document.getElementById('panel').shadowRoot
      .querySelector(`#schedule-when-seg button[data-mode="${m}"]`).click();
  }, mode);
}

test.describe('Scheduled events', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('the shelf hosts both the library button and the desk calendar with today\'s date', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });

    const shelf = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      const shelfEl = root.querySelector('.library-shelf');
      return {
        tag: shelfEl.tagName,
        hasLibraryBtn: !!shelfEl.querySelector('button#library-open-btn'),
        hasCalendarBtn: !!shelfEl.querySelector('button#schedule-calendar-btn'),
        day: root.getElementById('shelf-calendar-day').textContent,
        month: root.getElementById('shelf-calendar-month').textContent,
      };
    });
    // A button can't nest a button, so the shelf itself must not be one.
    expect(shelf.tag).toBe('DIV');
    expect(shelf.hasLibraryBtn).toBe(true);
    expect(shelf.hasCalendarBtn).toBe(true);
    expect(shelf.day).toBe(String(new Date().getDate()));
    expect(shelf.month.length).toBeGreaterThan(1);
    expect(pageErrors).toEqual([]);
  });

  test('the calendar popup shows a seeded event as a chip and in the day list', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS,
      schedules: [todayOnceSchedule()],
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);

    const state = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      const chips = [...root.querySelectorAll('#cal-grid .cal-chip')].map((c) => c.textContent);
      const events = [...root.querySelectorAll('#cal-day-list .cal-event .cal-event-name')].map((e) => e.textContent);
      return { chips, events, title: root.getElementById('cal-title').textContent };
    });
    expect(state.chips).toContain('Seeded Event');
    // The popup opens on today, and the seeded event is today.
    expect(state.events).toContain('Seeded Event');
    expect(state.title.length).toBeGreaterThan(4);
  });

  test('recurring weekly events render on every matching weekday of the month', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS,
      schedules: [{
        schedule_id: 'schedule_weekly',
        name: 'Sunday Art',
        action: { type: 'scene', scene_id: 'scene_fall' },
        trigger: { type: 'recurring', freq: 'weekly', time: '06:00', days: [6] }, // Sun (Mon=0)
      }],
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);

    const sundaysWithChip = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('#cal-grid .cal-day')]
        .filter((cell) => [...cell.querySelectorAll('.cal-chip')].some((c) => c.textContent === 'Sunday Art'))
        .map((cell) => new Date(`${cell.dataset.date}T12:00`).getDay());
    });
    // Rendered on at least 4 days (a 6-week grid always spans ≥6 Sundays,
    // 4+ inside the visible month) and *only* on JS-Sunday (getDay 0).
    expect(sundaysWithChip.length).toBeGreaterThanOrEqual(4);
    expect(new Set(sundaysWithChip)).toEqual(new Set([0]));
  });

  test('"＋ New event" creates a once schedule for a scene via On a date', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);
    await clickPanelButton(page, 'schedule-new-btn');
    await waitForDialog(page);

    await setDialogName(page, 'Fall opening day');
    await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('schedule-action-scene').value = 'scene_fall';
      root.getElementById('schedule-once-at').value = '2027-09-26T06:00';
    });
    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none'
    );

    expect(mockServer.schedules).toHaveLength(1);
    expect(mockServer.schedules[0]).toMatchObject({
      name: 'Fall opening day',
      action: { type: 'scene', scene_id: 'scene_fall' },
      trigger: { type: 'once', at: '2027-09-26T06:00' },
    });
  });

  test('"In…" is sugar: it posts a plain once trigger at now + duration', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);
    await clickPanelButton(page, 'schedule-new-btn');
    await waitForDialog(page);

    await setDialogName(page, 'Soon');
    await panelEval(page, () => {
      document.getElementById('panel').shadowRoot.getElementById('schedule-action-scene').value = 'scene_fall';
    });
    await pickWhenMode(page, 'in');
    const before = Date.now();
    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel.shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none';
    });

    const record = mockServer.schedules[0];
    // The backend never sees "relative": same shape as an On-a-date record.
    expect(record.trigger.type).toBe('once');
    expect(Object.keys(record.trigger).sort()).toEqual(['at', 'type']);
    const at = new Date(record.trigger.at).getTime();
    const expected = before + 3600000; // dialog defaults to "in 1 hour"
    expect(Math.abs(at - expected)).toBeLessThan(2 * 60000); // minute precision + test slack
  });

  test('weekly repeat requires at least one weekday, then posts the picked days', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);
    await clickPanelButton(page, 'schedule-new-btn');
    await waitForDialog(page);

    await setDialogName(page, 'Weekend art');
    await panelEval(page, () => {
      document.getElementById('panel').shadowRoot.getElementById('schedule-action-scene').value = 'scene_fall';
    });
    await pickWhenMode(page, 'repeat');
    await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('schedule-repeat-freq').value = 'weekly';
      root.getElementById('schedule-repeat-freq').dispatchEvent(new Event('change'));
      root.getElementById('schedule-repeat-time').value = '07:30';
    });

    // The slideshow nudge is visible in Repeat mode.
    const hintVisible = await panelEval(page, () => {
      const el = document.getElementById('panel').shadowRoot.querySelector('.schedule-slideshow-hint');
      return !!el && el.offsetParent !== null && /Slideshow/.test(el.textContent);
    });
    expect(hintVisible).toBe(true);

    // No weekday picked yet → validation error, nothing posted.
    await clickPanelButton(page, 'schedule-dialog-save');
    const fb = await getFeedback(page, 'schedule-dialog-fb');
    expect(fb.className).toContain('err');
    expect(fb.text).toContain('weekday');
    expect(mockServer.schedules).toHaveLength(0);

    // Pick Sat + Sun and save.
    await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('#schedule-repeat-days button[data-day="5"]').click();
      root.querySelector('#schedule-repeat-days button[data-day="6"]').click();
    });
    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none'
    );
    expect(mockServer.schedules[0].trigger).toEqual({
      type: 'recurring', freq: 'weekly', time: '07:30', days: [5, 6],
    });
  });

  test('the wall\'s Schedule… button pre-fills the selected saved scene', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await selectWallScene(page, 'scene_fall');

    await clickPanelButton(page, 'wall-schedule-btn');
    await waitForDialog(page);

    const dialog = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        summaryShown: root.getElementById('schedule-action-summary-row').style.display !== 'none',
        pickerShown: root.getElementById('schedule-action-picker').style.display !== 'none',
        summary: root.getElementById('schedule-action-summary').textContent,
        name: root.getElementById('schedule-name').value,
      };
    });
    expect(dialog.summaryShown).toBe(true);
    expect(dialog.pickerShown).toBe(false);
    expect(dialog.summary).toContain('Fall Colors');
    expect(dialog.name).toBe('Fall Colors');

    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none'
    );
    expect(mockServer.schedules[0].action).toEqual({ type: 'scene', scene_id: 'scene_fall' });
    // Confirmation surfaces on the wall (the popup isn't open here).
    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.text).toContain('Scheduled');
  });

  test('with unsaved wall changes, Schedule… asks to save the scene first', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: [], images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    // Stage a pick without saving any scene.
    await panelEval(page, () => {
      const panel = document.getElementById('panel');
      panel._wallPendingMappings.entry_1 = 'image_vacation';
    });

    // First dialog: "save as a scene now?" confirm; second: the scene name prompt.
    const dialogMessages = [];
    page.on('dialog', (dialog) => {
      dialogMessages.push(dialog.message());
      dialog.accept(dialog.type() === 'prompt' ? 'My Evening Wall' : undefined);
    });
    await clickPanelButton(page, 'wall-schedule-btn');
    await waitForDialog(page);

    expect(dialogMessages[0]).toContain('saved scene');
    expect(mockServer.scenes).toHaveLength(1);
    expect(mockServer.scenes[0].name).toBe('My Evening Wall');
    const summary = await panelEval(page,
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-action-summary').textContent
    );
    expect(summary).toContain('My Evening Wall');
  });

  test('the per-tile picker\'s Schedule… pre-fills a single-image action', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: [], images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await createWall(page, 'Living Room');
    const canvasBox = await panelEval(page, () => {
      const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
      return { x: r.x, y: r.y };
    });
    await dragFirstPaletteItemTo(page, canvasBox.x + 100, canvasBox.y + 80);
    await page.waitForTimeout(100);
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      (id) => !!document.getElementById('panel').shadowRoot
        .querySelector(`#wall-image-picker-grid .image-picker-cell[data-image-id="${id}"]`),
      'image_family'
    );

    // Schedule is disabled until a library image is picked.
    let disabled = await panelEval(page,
      () => document.getElementById('panel').shadowRoot.getElementById('wall-picker-schedule-btn').disabled
    );
    expect(disabled).toBe(true);

    // Picking stages the image and closes the picker; reopening shows the
    // pick selected with Schedule… now armed.
    await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      [...root.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
        .find((c) => c.dataset.imageId === 'image_family').click();
    });
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'none'
    );
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot
        .querySelectorAll('#wall-image-picker-grid .image-picker-cell.selected').length === 1
    );
    disabled = await panelEval(page,
      () => document.getElementById('panel').shadowRoot.getElementById('wall-picker-schedule-btn').disabled
    );
    expect(disabled).toBe(false);

    await clickPanelButton(page, 'wall-picker-schedule-btn');
    await waitForDialog(page);

    // The picker closed behind the dialog and the action is fixed.
    const state = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        pickerDisplay: root.getElementById('wall-image-picker-overlay').style.display,
        summary: root.getElementById('schedule-action-summary').textContent,
        name: root.getElementById('schedule-name').value,
      };
    });
    expect(state.pickerDisplay).toBe('none');
    expect(state.summary).toContain('Living Room Frame');
    expect(state.name).toContain('Living Room Frame');

    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none'
    );
    expect(mockServer.schedules[0].action).toEqual({
      type: 'image', entry_id: 'entry_1', image_id: 'image_family',
    });
  });

  test('day-list toggle disables, edit round-trips, delete removes', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, images: IMAGES, albums: ALBUMS,
      schedules: [todayOnceSchedule()],
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#cal-day-list .cal-event').length === 1
    );

    // Toggle off → POST { enabled: false } and a muted re-render.
    await panelEval(page, () => {
      const box = document.getElementById('panel').shadowRoot.querySelector('#cal-day-list .cal-event-enabled');
      box.checked = false;
      box.dispatchEvent(new Event('change'));
    });
    await page.waitForFunction(() => {
      const el = document.getElementById('panel').shadowRoot.querySelector('#cal-day-list .cal-event');
      return el && el.className.includes('muted');
    });
    expect(mockServer.schedules[0].enabled).toBe(false);

    // Edit → dialog opens pre-filled with the record's own values.
    await panelEval(page, () => {
      document.getElementById('panel').shadowRoot.querySelector('#cal-day-list .cal-event-edit').click();
    });
    await waitForDialog(page);
    const prefill = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        name: root.getElementById('schedule-name').value,
        at: root.getElementById('schedule-once-at').value,
        title: root.getElementById('schedule-dialog-title').textContent,
      };
    });
    expect(prefill.name).toBe('Seeded Event');
    expect(prefill.at).toBe(todayOnceSchedule().trigger.at);
    expect(prefill.title).toContain('Edit');
    await setDialogName(page, 'Renamed Event');
    await clickPanelButton(page, 'schedule-dialog-save');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('schedule-dialog-overlay').style.display === 'none'
    );
    expect(mockServer.schedules[0].name).toBe('Renamed Event');

    // Delete (accepting the confirm) → record gone, list empties.
    page.once('dialog', (dialog) => dialog.accept());
    await panelEval(page, () => {
      document.getElementById('panel').shadowRoot.querySelector('#cal-day-list .cal-event-delete').click();
    });
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#cal-day-list .cal-event').length === 0
    );
    expect(mockServer.schedules).toHaveLength(0);
  });

  test('a target_missing schedule renders broken instead of vanishing', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: [], images: IMAGES, albums: ALBUMS,
      schedules: [{
        ...todayOnceSchedule(),
        enabled: false,
        status: 'target_missing',
        action: { type: 'scene', scene_id: 'scene_deleted' },
      }],
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openCalendarPopup(page);

    const state = await panelEval(page, () => {
      const root = document.getElementById('panel').shadowRoot;
      const chip = [...root.querySelectorAll('#cal-grid .cal-chip')].find((c) => c.textContent === 'Seeded Event');
      const note = root.querySelector('#cal-day-list .cal-event-note');
      const detail = root.querySelector('#cal-day-list .cal-event-detail');
      return {
        chipClass: chip ? chip.className : null,
        note: note ? note.textContent : null,
        detail: detail ? detail.textContent : null,
      };
    });
    expect(state.chipClass).toContain('broken');
    expect(state.note).toContain('deleted');
    expect(state.detail).toContain('deleted');
  });
});
