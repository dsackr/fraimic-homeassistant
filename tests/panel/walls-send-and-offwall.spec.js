// Coverage for "Send to Frames": pushes whatever's currently previewed for
// every known frame straight to the physical frames via
// /api/fraimic/library/send. A frame works the same whether it's placed on
// the wall's canvas or still sitting in the palette -- clicking either one
// opens the same image picker, and Send to Frames posts to both alike, not
// just placed tiles.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  clickPaletteItem,
  pickImageInWallPicker,
  selectWallScene,
  getWallPaletteItems,
  clickPanelButton,
  getFeedback,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'auto' },
  { entry_id: 'entry_3', title: 'Bedroom Frame', width: 800, height: 480, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
  { image_id: 'image_2', filename: 'two.png', albums: [] },
];

// Places only entry_1 and entry_2 on the wall -- entry_3 stays unplaced in
// the palette so it can be used as an "off-wall" frame that a loaded scene
// still maps.
async function buildWallWithTwoFrames(page) {
  await openScenesTab(page);
  await createWall(page, 'Living Room');
  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
  await dragFirstPaletteItemTo(page, canvasBox.x + 80, canvasBox.y + 60);
  await page.waitForTimeout(100);
  await dragFirstPaletteItemTo(page, canvasBox.x + 300, canvasBox.y + 60);
  await page.waitForTimeout(100);
}

test.describe('Send to Frames and off-wall frames', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      scenes: [{
        scene_id: 'scene_1',
        name: 'Test Scene',
        mappings: { entry_1: 'image_1', entry_3: 'image_2' }, // entry_3 is never placed on the wall
      }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Send to Frames posts every frame\'s effective image, on the wall or off it', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(200);

    // entry_2 has no mapping in scene_1 yet -- pick one so all three frames
    // (two placed, one still in the palette) have an image to send.
    await clickTile(page, 'entry_2');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );
    await pickImageInWallPicker(page, 'image_2');
    await page.waitForTimeout(200);

    await clickPanelButton(page, 'wall-send-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('ok');
    expect(fb.text).toContain('Sent to 3 frames');

    const sent = mockServer.sends.map((s) => ({ entity_id: s.entity_id, image_id: s.image_id }));
    expect(sent.sort((a, b) => a.entity_id.localeCompare(b.entity_id))).toEqual([
      { entity_id: 'sensor.entry_1_battery', image_id: 'image_1' },
      { entity_id: 'sensor.entry_2_battery', image_id: 'image_2' },
      { entity_id: 'sensor.entry_3_battery', image_id: 'image_2' },
    ]);
  });

  test('Send to Frames reports an error when no frame has an image', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page); // no scene loaded, no pending picks

    await clickPanelButton(page, 'wall-send-btn');
    await page.waitForTimeout(100);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('err');
    expect(mockServer.sends).toHaveLength(0);
  });

  test('a frame not on this wall still shows its scene image and can be re-picked/cleared', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(200);

    let palette = await getWallPaletteItems(page);
    let entry3 = palette.find((p) => p.entryId === 'entry_3');
    expect(entry3.hasImg).toBe(true); // mapped in scene_1, even though it's not placed

    // Clicking it (not dragging) opens the same image picker a placed tile
    // would -- clearing the image works identically either way.
    await clickPaletteItem(page, 'entry_3');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );
    await clickPanelButton(page, 'wall-image-picker-clear');
    await page.waitForTimeout(100);

    palette = await getWallPaletteItems(page);
    entry3 = palette.find((p) => p.entryId === 'entry_3');
    expect(entry3.hasImg).toBe(false);

    await clickPanelButton(page, 'wall-save-scene-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('ok');

    const savedScene = mockServer.scenes.find((s) => s.scene_id === 'scene_1');
    expect(savedScene.mappings).toEqual({ entry_1: 'image_1' }); // entry_3 cleared, entry_1 untouched
  });
});
