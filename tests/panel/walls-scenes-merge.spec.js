// Coverage for the Scenes/Walls tab merge itself: the Scenes tab is now the
// wall canvas directly (no picking a wall first -- the first saved wall
// loads automatically, or an empty draft wall is ready immediately if none
// exist yet), the scene picker defaults to "Create New…" with no separate
// "New Scene"/"Save As New Scene" affordances, an existing scene can be
// deleted from right there, and selecting a frame surfaces small
// portrait/landscape orientation icons that update the frame immediately.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  dragFirstPaletteItemTo,
  clickPaletteItem,
  selectWallScene,
  clickPanelButton,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];

test.describe('Scenes tab is the wall canvas', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('a saved wall loads automatically -- no wall picker step required', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      walls: [{ wall_id: 'wall_1', name: 'Living Room', placements: { entry_1: { x: 20, y: 20 } } }],
    });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return !!root.querySelector('.wall-tile[data-entry-id="entry_1"]');
    }, { timeout: 5000 });

    const selectValue = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-select').value
    );
    expect(selectValue).toBe('wall_1');
  });

  test('with no wall saved yet, the canvas is ready immediately and Save Layout prompts for a name', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    // No dialog needed to see a usable canvas -- unlike createWall(), this
    // exercises the draft-wall path directly.
    const canvasBox = await page.evaluate(() => {
      const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
      return { x: r.x, y: r.y };
    });
    await dragFirstPaletteItemTo(page, canvasBox.x + 80, canvasBox.y + 60);
    await page.waitForTimeout(100);

    page.once('dialog', (dialog) => dialog.accept('Living Room'));
    await clickPanelButton(page, 'wall-save-layout-btn');
    await page.waitForTimeout(300);

    expect(mockServer.walls).toHaveLength(1);
    expect(mockServer.walls[0].name).toBe('Living Room');
    expect(Object.keys(mockServer.walls[0].placements)).toEqual(['entry_1']);

    const selectValue = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-select').value
    );
    expect(selectValue).toBe(mockServer.walls[0].wall_id);
  });

  test('the scene picker defaults to "Create New…", not a saved scene, and has no separate new-scene button', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      scenes: [{ scene_id: 'scene_1', name: 'Test Scene', mappings: { entry_1: 'image_1' } }],
    });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    await page.waitForFunction(() => {
      const sel = document.getElementById('panel').shadowRoot.getElementById('wall-scene-select');
      return [...sel.options].some((o) => o.value === 'scene_1');
    });

    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const sel = root.getElementById('wall-scene-select');
      return {
        value: sel.value,
        firstOptionLabel: sel.options[0].textContent,
        hasSaveAsNewBtn: !!root.getElementById('wall-save-new-scene-btn'),
        hasNewSceneBtn: !!root.getElementById('scene-new-btn'),
      };
    });
    expect(state.value).toBe('');
    expect(state.firstOptionLabel).toBe('Create New…');
    expect(state.hasSaveAsNewBtn).toBe(false);
    expect(state.hasNewSceneBtn).toBe(false);
  });

  test('Delete Scene removes the active scene and resets the picker to Create New…', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      scenes: [{ scene_id: 'scene_1', name: 'Test Scene', mappings: { entry_1: 'image_1' } }],
    });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(100);

    const visibleBefore = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-delete-scene-btn').style.display
    );
    expect(visibleBefore).not.toBe('none');

    page.once('dialog', (dialog) => dialog.accept());
    await clickPanelButton(page, 'wall-delete-scene-btn');
    await page.waitForTimeout(200);

    expect(mockServer.scenes.find((s) => s.scene_id === 'scene_1')).toBeUndefined();
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        selectValue: root.getElementById('wall-scene-select').value,
        deleteBtnDisplay: root.getElementById('wall-delete-scene-btn').style.display,
      };
    });
    expect(state.selectValue).toBe('');
    expect(state.deleteBtnDisplay).toBe('none');
  });

  test('clicking a frame surfaces orientation icons that update the frame immediately', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await clickPaletteItem(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );

    const before = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        portraitVisible: root.getElementById('wall-image-picker-portrait').style.display !== 'none',
        portraitActive: root.getElementById('wall-image-picker-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('wall-image-picker-landscape').classList.contains('active'),
      };
    });
    expect(before.portraitVisible).toBe(true);
    expect(before.portraitActive).toBe(false);
    expect(before.landscapeActive).toBe(false);

    await clickPanelButton(page, 'wall-image-picker-portrait');
    await page.waitForTimeout(100);

    const calls = await page.evaluate(() => window.__serviceCalls);
    expect(calls).toContainEqual({
      domain: 'select',
      service: 'select_option',
      data: { entity_id: 'select.entry_1_orientation', option: 'Portrait' },
    });

    const after = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        portraitActive: root.getElementById('wall-image-picker-portrait').classList.contains('active'),
        frameOrientation: document.getElementById('panel')._frames.find((f) => f.entryId === 'entry_1').orientation,
      };
    });
    expect(after.portraitActive).toBe(true);
    expect(after.frameOrientation).toBe('portrait');
  });
});
