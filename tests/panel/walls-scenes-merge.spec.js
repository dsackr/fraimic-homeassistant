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
  clickTile,
  dragTileBy,
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

  test('the default wall loads automatically -- no wall picker step, custom walls still selectable', async ({ page }) => {
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

    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const sel = root.getElementById('wall-select');
      return {
        value: sel.value,
        firstOption: sel.options[0].textContent,
        optionValues: [...sel.options].map((o) => o.value),
      };
    });
    expect(state.value).toBe('default');
    expect(state.firstOption).toBe('All Frames');
    expect(state.optionValues).toContain('wall_1');
  });

  test('the default wall places every frame, hides delete/remove, and auto-saves drags', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    // Every configured frame is already placed -- no palette items, no ✕
    // remove buttons, no Delete Wall, no Save Layout button at all.
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        tiles: [...root.querySelectorAll('.wall-tile')].map((t) => t.dataset.entryId),
        paletteItems: root.querySelectorAll('.wall-palette-item').length,
        removeBtns: root.querySelectorAll('.tile-remove-btn').length,
        deleteBtnHidden: root.getElementById('wall-delete-btn').style.display === 'none',
        saveLayoutBtn: root.getElementById('wall-save-layout-btn'),
      };
    });
    expect(state.tiles).toEqual(['entry_1']);
    expect(state.paletteItems).toBe(0);
    expect(state.removeBtns).toBe(0);
    expect(state.deleteBtnHidden).toBe(true);
    expect(state.saveLayoutBtn).toBe(null);

    // Dragging a tile persists automatically (debounced ~800ms).
    await dragTileBy(page, 'entry_1', 200, 40);
    await page.waitForTimeout(1200);
    const saved = mockServer.walls.find((w) => w.wall_id === 'default');
    const seeded = { x: 0, y: 0 };
    expect(saved.placements.entry_1).not.toEqual(seeded);
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
    // Frames live on the default wall now, so the click target is a canvas
    // tile rather than a palette item -- same click→picker contract.
    await clickTile(page, 'entry_1');
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
