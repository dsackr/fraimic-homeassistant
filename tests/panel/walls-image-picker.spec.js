// Coverage for two picker UX fixes: the panel can be dragged out of the way
// so the wall canvas stays visible/reachable behind it, and an album filter
// narrows the grid instead of always listing the entire library.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openWallsSubTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
  getPickerGridImageIds,
  selectPickerAlbum,
  getPickerBoxRect,
  dragPickerBy,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_vacation', filename: 'beach.png', albums: ['Vacation'] },
  { image_id: 'image_family', filename: 'reunion.png', albums: ['Family'] },
  { image_id: 'image_unsorted', filename: 'misc.png', albums: [] },
];
const ALBUMS = [
  { name: 'Vacation', count: 1, cover_image_id: 'image_vacation' },
  { name: 'Family', count: 1, cover_image_id: 'image_family' },
];

async function openPickerOnFirstTile(page) {
  await openWallsSubTab(page);
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

test.describe('Wall image picker', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('defaults to showing every album\'s images', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);

    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    const ids = await getPickerGridImageIds(page);
    expect(ids.sort()).toEqual(['image_family', 'image_unsorted', 'image_vacation']);
  });

  test('filtering by album narrows the grid to that album only', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );

    await selectPickerAlbum(page, 'Vacation');
    await page.waitForFunction(
      () => {
        const ids = [...document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell')]
          .map((c) => c.dataset.imageId);
        return ids.length === 1;
      }
    );
    expect(await getPickerGridImageIds(page)).toEqual(['image_vacation']);

    // Switching back to "All Photos" (empty value) restores the full list.
    await selectPickerAlbum(page, '');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length === 3
    );
  });

  test('the picker panel can be dragged, and the wall stays clickable around it', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);

    const before = await getPickerBoxRect(page);
    await dragPickerBy(page, 120, 90);
    await page.waitForTimeout(100);
    const after = await getPickerBoxRect(page);

    expect(after.x).not.toBe(before.x);
    expect(after.y).not.toBe(before.y);

    // The overlay wrapper must not blanket-intercept clicks -- only the
    // panel box itself should, so the wall canvas underneath stays usable.
    const overlayPointerEvents = await page.evaluate(
      () => getComputedStyle(document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay')).pointerEvents
    );
    expect(overlayPointerEvents).toBe('none');
  });
});
