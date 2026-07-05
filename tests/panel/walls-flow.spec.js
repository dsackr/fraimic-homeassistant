// End-to-end coverage of the Walls save/preview/edit flow: Save Layout
// persisting, loading a scene onto a wall, picking a new image for one tile
// without disturbing another tile's thumbnail (regression for the
// full-cache-wipe flicker bug fixed alongside "scene no longer exists"),
// and the merge-on-save semantics that must never clobber mappings for
// frames outside the wall being edited.

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
  getWallTiles,
  clickPanelButton,
  getFeedback,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_1', filename: 'one.png', albums: [] },
  { image_id: 'image_2', filename: 'two.png', albums: [] },
];

async function buildWallWithBothFrames(page, mockServer) {
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

test.describe('Walls save/preview/edit flow', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      scenes: [{ scene_id: 'scene_1', name: 'Test Scene', mappings: { entry_1: 'image_1' } }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Save Layout persists placements to the backend', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithBothFrames(page, mockServer);

    await clickPanelButton(page, 'wall-save-layout-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-fb');
    expect(fb.className).toContain('ok');
    expect(fb.text).toContain('saved');

    expect(mockServer.walls).toHaveLength(1);
    expect(Object.keys(mockServer.walls[0].placements).sort()).toEqual(['entry_1', 'entry_2']);
  });

  test('selecting a scene previews its mappings on the wall', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithBothFrames(page, mockServer);

    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(300);

    const tiles = await getWallTiles(page);
    const entry1 = tiles.find((t) => t.entryId === 'entry_1');
    const entry2 = tiles.find((t) => t.entryId === 'entry_2');
    expect(entry1.hasImg).toBe(true); // mapped in scene_1
    expect(entry2.hasImg).toBe(false); // not mapped -- shows the frame-title placeholder
  });

  test('picking a new image for one tile does not blank or refetch another tile\'s thumbnail', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithBothFrames(page, mockServer);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(300);

    const before = await getWallTiles(page);
    const entry1Before = before.find((t) => t.entryId === 'entry_1');
    expect(entry1Before.hasImg).toBe(true);

    mockServer.requestLog.length = 0;
    await clickTile(page, 'entry_2');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'flex'
    );
    await pickImageInWallPicker(page, 'image_2');
    await page.waitForTimeout(300);

    const after = await getWallTiles(page);
    const entry1After = after.find((t) => t.entryId === 'entry_1');
    const entry2After = after.find((t) => t.entryId === 'entry_2');

    // The untouched tile keeps its exact thumbnail (same blob: URL) instead
    // of blanking and re-fetching -- this is the regression check for the
    // full-cache-wipe bug.
    expect(entry1After.imgSrc).toBe(entry1Before.imgSrc);
    expect(entry2After.hasImg).toBe(true);

    // The image picker's own grid legitimately fetches a thumbnail for
    // every library image (including image_1, to show it as a pickable
    // option) -- that's one expected fetch. A second one would mean the
    // wall canvas itself re-fetched image_1 for entry_1's unchanged tile,
    // which is the flicker bug this test guards against.
    const image1Fetches = mockServer.requestLog.filter((r) => r.includes('/library/image/image_1')).length;
    expect(image1Fetches).toBeLessThanOrEqual(1);
  });

  test('Save to Scene merges this wall\'s edits without touching other mappings', async ({ page }) => {
    // scene_1 also maps a frame that isn't on this wall at all -- Save to
    // Scene must round-trip that mapping untouched.
    mockServer.scenes[0].mappings.entry_offwall = 'image_1';

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await buildWallWithBothFrames(page, mockServer);
    await selectWallScene(page, 'scene_1');
    await page.waitForTimeout(200);

    await clickTile(page, 'entry_2');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'flex'
    );
    await pickImageInWallPicker(page, 'image_2');
    await page.waitForTimeout(200);

    await clickPanelButton(page, 'wall-save-scene-btn');
    await page.waitForTimeout(300);

    const fb = await getFeedback(page, 'wall-scene-fb');
    expect(fb.className).toContain('ok');

    const savedScene = mockServer.scenes.find((s) => s.scene_id === 'scene_1');
    expect(savedScene.mappings).toEqual({
      entry_1: 'image_1',
      entry_2: 'image_2',
      entry_offwall: 'image_1', // untouched -- not placed on this wall
    });
  });
});
