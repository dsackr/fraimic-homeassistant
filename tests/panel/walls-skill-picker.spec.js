// Coverage for the wall picker's "Skills" filter: a skill (Word/Joke/Quote/
// Scripture of the Day, or an image feed/album -- see skills.py) can be
// assigned to a wall tile the same way a photo is, staged client-side, and
// round-tripped through Save Scene as a `{type:'skill', skill_id}` mapping
// instead of a bare image_id.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  selectPickerAlbum,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const SKILLS = [
  { skill_id: 'skill_word', name: 'Word of the Day', content_mode: 'word' },
  { skill_id: 'skill_joke', name: 'Joke of the Day', content_mode: 'joke' },
];

async function openPickerOnFirstTile(page) {
  await openScenesTab(page);
  await createWall(page, 'Living Room');
  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
  await dragFirstPaletteItemTo(page, canvasBox.x + 100, canvasBox.y + 80);
  await page.waitForTimeout(100);
  await clickTile(page, 'entry_1');
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
  );
}

function getPickerGridSkillIds(page) {
  return page.evaluate(() =>
    [...document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
      .map((c) => c.dataset.skillId)
  );
}

async function selectSkillInPicker(page, skillId) {
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const cell = [...root.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
      .find((c) => c.dataset.skillId === id);
    cell.click();
  }, skillId);
}

test.describe('Wall picker: Skills', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, skills: SKILLS });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('the Skills filter lists every skill', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);

    await selectPickerAlbum(page, '__skills__');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    expect((await getPickerGridSkillIds(page)).sort()).toEqual(['skill_joke', 'skill_word']);
  });

  test('picking a skill stages it and renders the tile as an icon+label with a "skill" badge', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);

    await selectPickerAlbum(page, '__skills__');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    await selectSkillInPicker(page, 'skill_word');

    // Picking closes the picker (same as a photo pick).
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'none'
    );

    const tile = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const t = [...root.querySelectorAll('.wall-tile')].find((el) => el.dataset.entryId === 'entry_1');
      const badge = t.querySelector('.wall-tile-badge');
      return {
        label: t.querySelector('.wall-tile-skill-label') && t.querySelector('.wall-tile-skill-label').textContent,
        badgeKind: badge.dataset.kind,
        badgeText: badge.textContent,
      };
    });
    expect(tile.label).toBe('Word of the Day');
    // Staged this session (not yet part of any saved scene) -- same
    // "staged" precedence a fresh photo pick gets.
    expect(tile.badgeKind).toBe('staged');
    expect(tile.badgeText).toBe('staged');
  });

  test('Save Scene persists the skill mapping as {type:"skill", skill_id}', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);
    await selectPickerAlbum(page, '__skills__');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    await selectSkillInPicker(page, 'skill_word');

    page.once('dialog', (dialog) => dialog.accept('My Skill Scene'));
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-save-scene-btn').click();
    });

    await expect.poll(() => mockServer.scenes.length).toBe(1);
    expect(mockServer.scenes[0].mappings).toEqual({
      entry_1: { type: 'skill', skill_id: 'skill_word' },
    });
  });

  test('a skill mapping cannot be sent via the picker\'s instant Send button', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);
    await selectPickerAlbum(page, '__skills__');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    await selectSkillInPicker(page, 'skill_word');

    // Re-open the picker on the same tile -- the Send button reflects the
    // now-staged skill mapping.
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );
    const sendDisabled = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-picker-send-btn').disabled
    );
    expect(sendDisabled).toBe(true);
  });
});
