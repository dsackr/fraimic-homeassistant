// Coverage for two Walls features:
// - "Send to Frames": pushes whatever's currently previewed on the wall's
//   placed tiles straight to the physical frames via /api/fraimic/library/send.
// - The "Also assigned in this scene (not on this wall)" section: a loaded
//   scene may map frames that aren't part of this wall's layout at all --
//   those still get surfaced (with a thumbnail) so the user isn't surprised
//   by a stale mapping, and can be cleared from here.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openWallsSubTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  pickImageInWallPicker,
  selectWallScene,
  getWallOffWallEntries,
  clickWallOffWallClear,
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

// Places only entry_1 and entry_2 on the wall -- entry_3 stays unplaced so it
// can be used as an "off-wall" frame that a loaded scene still maps.
async function buildWallWithTwoFrames(page) {
  await openWallsSubTab(page);
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

test.describe('Send to Frames and off-wall scene mappings', () => {
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

  test('Send to Frames posts each placed tile\'s effective image to its frame', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(200);

    // entry_2 has no mapping in scene_1 yet -- pick one so both placed tiles
    // have an image to send.
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
    expect(fb.text).toContain('Sent to 2 frames');

    const sent = mockServer.sends.map((s) => ({ entity_id: s.entity_id, image_id: s.image_id }));
    expect(sent.sort((a, b) => a.entity_id.localeCompare(b.entity_id))).toEqual([
      { entity_id: 'sensor.entry_1_battery', image_id: 'image_1' },
      { entity_id: 'sensor.entry_2_battery', image_id: 'image_2' },
    ]);
  });

  test('Send to Frames reports an error when no placed tile has an image', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page); // no scene loaded, no pending picks

    await clickPanelButton(page, 'wall-send-btn');
    await page.waitForTimeout(100);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('err');
    expect(mockServer.sends).toHaveLength(0);
  });

  test('a scene mapping for a frame not on this wall shows with a thumbnail and can be cleared', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithTwoFrames(page);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(200);

    let offWall = await getWallOffWallEntries(page);
    expect(offWall).toHaveLength(1);
    expect(offWall[0].entryId).toBe('entry_3');
    expect(offWall[0].title).toBe('Bedroom Frame');
    expect(offWall[0].hasImg).toBe(true);

    await clickWallOffWallClear(page, 'entry_3');
    await page.waitForTimeout(100);

    offWall = await getWallOffWallEntries(page);
    expect(offWall).toHaveLength(0);

    await clickPanelButton(page, 'wall-save-scene-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('ok');

    const savedScene = mockServer.scenes.find((s) => s.scene_id === 'scene_1');
    expect(savedScene.mappings).toEqual({ entry_1: 'image_1' }); // entry_3 cleared, entry_1 untouched
  });
});
