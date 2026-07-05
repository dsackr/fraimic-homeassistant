// Add-on scenes ship bound to the single album their images were installed
// into (see ScenePackManager -- every pack image is uploaded into, and the
// pack's auto-built scene is scoped to, the same album name). User-made
// scenes have no such binding. On the wall:
//   - opening the picker for a tile defaults the album filter to the addon
//     scene's own album instead of "All Photos"
//   - the filter can still be changed freely
//   - but picking an image while filtered to a different album disables
//     Save to Scene for the rest of this session (Save As New Scene never is)
//   - re-picking from the locked album re-enables it (this is live derived
//     state, not a one-way latch)

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openWallsSubTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  pickImageInWallPicker,
  selectPickerAlbum,
  selectWallScene,
  clickPanelButton,
  getFeedback,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_pack_1', filename: 'pack1.png', albums: ['Holiday Pack'] },
  { image_id: 'image_pack_2', filename: 'pack2.png', albums: ['Holiday Pack'] },
  { image_id: 'image_other', filename: 'other.png', albums: ['Vacation'] },
];
const ALBUMS = [
  { name: 'Holiday Pack', count: 2, cover_image_id: 'image_pack_1' },
  { name: 'Vacation', count: 1, cover_image_id: 'image_other' },
];

function getAlbumSelectValue(page) {
  return page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-album').value);
}

function getSaveToSceneState(page) {
  return page.evaluate(() => {
    const btn = document.getElementById('panel').shadowRoot.getElementById('wall-save-scene-btn');
    return { disabled: btn.disabled, title: btn.title };
  });
}

async function buildWallOnFirstFrame(page) {
  await openWallsSubTab(page);
  await createWall(page, 'Living Room');
  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
  await dragFirstPaletteItemTo(page, canvasBox.x + 80, canvasBox.y + 60);
  await page.waitForTimeout(100);
}

async function waitForPickerOpen(page) {
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
  );
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
  );
}

test.describe('Add-on scene album lock', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      albums: ALBUMS,
      scenes: [
        { scene_id: 'addon_scene', name: 'Holiday Pack', mappings: { entry_1: 'image_pack_1' }, album: 'Holiday Pack', source: 'addon' },
        { scene_id: 'user_scene', name: 'My Scene', mappings: { entry_1: 'image_other' }, album: 'Vacation', source: 'user' },
      ],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('picker defaults to the addon scene\'s own album, not "All Photos"', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'addon_scene');
    await page.waitForTimeout(150);

    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);

    expect(await getAlbumSelectValue(page)).toBe('Holiday Pack');
  });

  test('picker defaults to "All Photos" for a user-made scene', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'user_scene');
    await page.waitForTimeout(150);

    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);

    expect(await getAlbumSelectValue(page)).toBe('');
  });

  test('picking from the locked album keeps Save to Scene enabled', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'addon_scene');
    await page.waitForTimeout(150);

    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);
    await pickImageInWallPicker(page, 'image_pack_2'); // still within "Holiday Pack"
    await page.waitForTimeout(150);

    expect((await getSaveToSceneState(page)).disabled).toBe(false);
  });

  test('picking from a different album disables Save to Scene but not Save As New Scene', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'addon_scene');
    await page.waitForTimeout(150);

    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);
    await selectPickerAlbum(page, 'Vacation');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length === 1
    );
    await pickImageInWallPicker(page, 'image_other');
    await page.waitForTimeout(150);

    const saveToScene = await getSaveToSceneState(page);
    expect(saveToScene.disabled).toBe(true);
    expect(saveToScene.title).toContain('Holiday Pack');

    const saveAsNewDisabled = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-save-new-scene-btn').disabled
    );
    expect(saveAsNewDisabled).toBe(false);

    // Backstop check inside _saveWallToScene itself, in case it's ever
    // invoked some other way than clicking the (now-disabled) button.
    await page.evaluate(() => document.getElementById('panel')._saveWallToScene());
    await page.waitForTimeout(150);
    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('err');
    expect(fb.text).toContain('Holiday Pack');
  });

  test('re-picking from the locked album re-enables Save to Scene', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'addon_scene');
    await page.waitForTimeout(150);

    // First pick off-album, disabling the button.
    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);
    await selectPickerAlbum(page, 'Vacation');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length === 1
    );
    await pickImageInWallPicker(page, 'image_other');
    await page.waitForTimeout(150);
    expect((await getSaveToSceneState(page)).disabled).toBe(true);

    // Re-open the same tile and pick back from the locked album.
    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);
    expect(await getAlbumSelectValue(page)).toBe('Holiday Pack'); // defaults back to the lock, not the last-used filter
    await pickImageInWallPicker(page, 'image_pack_2');
    await page.waitForTimeout(150);

    expect((await getSaveToSceneState(page)).disabled).toBe(false);
  });

  test('Save As New Scene succeeds even with an off-album pick', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    // buildWallOnFirstFrame's createWall() consumes its own dialog (the
    // wall name prompt) -- registering the scene-name dialog handler only
    // now, right before it's actually needed, keeps page.once() from
    // answering the wrong prompt.
    await buildWallOnFirstFrame(page);
    await selectWallScene(page, 'addon_scene');
    await page.waitForTimeout(150);

    await clickTile(page, 'entry_1');
    await waitForPickerOpen(page);
    await selectPickerAlbum(page, 'Vacation');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length === 1
    );
    await pickImageInWallPicker(page, 'image_other');
    await page.waitForTimeout(150);

    page.once('dialog', (dialog) => dialog.accept('My Holiday Remix'));
    await clickPanelButton(page, 'wall-save-new-scene-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('ok');
    const newScene = mockServer.scenes.find((s) => s.name === 'My Holiday Remix');
    expect(newScene.mappings).toEqual({ entry_1: 'image_other' });
    expect(newScene.source).toBe('user');
  });
});
