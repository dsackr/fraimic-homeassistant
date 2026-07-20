const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const PACK_IMAGE = {
  filename: 'cover.jpg',
  path: 'scene_packs/example/cover.jpg',
  title: 'Cover',
  source: 'Test',
};

const SCENE_PACKS = [
  {
    id: 'fast_animals',
    name: 'Fast Animals',
    description: 'Fast animal artwork.',
    category: ['speed', 'nature'],
    categories: ['speed', 'nature'],
    license: 'Public domain',
    cover: 'scene_packs/animals/preview_cover.jpg',
    images: [PACK_IMAGE],
  },
  {
    id: 'classic_art',
    name: 'Classic Art',
    description: 'Famous public-domain masterworks.',
    category: 'famous_artists',
    categories: ['famous_artists'],
    license: 'Public domain',
    cover: 'scene_packs/classic_art/preview_cover.jpg',
    images: [PACK_IMAGE],
  },
  {
    id: 'legacy_space',
    name: 'Legacy Space',
    description: 'A legacy pack with only the old category field.',
    category: 'space',
    license: 'Public domain',
    cover: 'scene_packs/space/preview_cover.jpg',
    images: [PACK_IMAGE],
  },
];

async function openAddons(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

function categoryTitles(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    return [...root.querySelectorAll('#art-categories-grid .category-tile-title')]
      .map((el) => el.textContent.trim());
  });
}

async function openCategory(page, title) {
  await page.evaluate((categoryTitle) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('#art-categories-grid .category-tile')]
      .find((el) => el.querySelector('.category-tile-title').textContent.trim() === categoryTitle);
    tile.click();
  }, title);
}

function visiblePackTitles(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    return [...root.querySelectorAll('#pack-grid .scene-card-title')]
      .map((el) => el.textContent.trim());
  });
}

test.describe('Gallery category tags', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ scenePacks: SCENE_PACKS });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('builds art categories from pack tags (Gallery is art-only)', async ({ page }) => {
    await gotoPanel(page, baseUrl);
    await openAddons(page);

    await expect.poll(() => categoryTitles(page)).toEqual([
      'Famous Artists',
      'Nature',
      'Speed',
      'Space',
    ]);
    // No Tools / productivity section after Content Platform Phase 6.
    await expect.poll(() => page.evaluate(() =>
      !!document.getElementById('panel').shadowRoot.getElementById('productivity-grid')
    )).toBe(false);

    await openCategory(page, 'Nature');
    await expect.poll(() => visiblePackTitles(page)).toEqual(['Fast Animals']);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('addons-crumb-back').click();
    });
    await openCategory(page, 'Speed');
    await expect.poll(() => visiblePackTitles(page)).toEqual(['Fast Animals']);
  });

  test('the image viewer closes on a backdrop click but not on the photo itself', async ({ page }) => {
    await gotoPanel(page, baseUrl);
    await openAddons(page);

    const overlayDisplay = () => page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('pack-preview-overlay').style.display
    );

    await page.evaluate(() => {
      const panel = document.getElementById('panel');
      panel._openPackPreview(panel._scenePacks[0], 0);
    });
    expect(await overlayDisplay()).toBe('flex');

    // Clicking the photo keeps the viewer open…
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('pack-preview-img').click();
    });
    expect(await overlayDisplay()).toBe('flex');

    // …clicking the greyed-out space beside it closes it.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('pack-preview-stage').click();
    });
    expect(await overlayDisplay()).toBe('none');
  });
});
