// Regression coverage for a real bug: the Add-ons tab's catalog
// (GET /api/fraimic/scene_packs) was only ever fetched once at initial
// panel load, plus after this session's own install/sync/uninstall
// actions. Switching tabs (_setTab) and reconnecting the panel element
// (_revive -- e.g. navigating away in the HA sidebar and back) never
// refetched, so a manifest update (packs added/removed upstream) was
// invisible to an already-open browser tab until a full page reload.
// _refreshScenePacksIfStale (throttled, 10s) now runs from both places.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const PACK_ONE = {
  id: 'pack_one', name: 'Pack One', description: 'First pack.',
  category: 'nature', categories: ['nature'], license: 'Public domain',
  cover: 'scene_packs/animals/preview_cover.jpg', images: [],
};
const PACK_TWO = {
  id: 'pack_two', name: 'Pack Two', description: 'Second pack, added later.',
  category: 'nature', categories: ['nature'], license: 'Public domain',
  cover: 'scene_packs/animals/preview_cover.jpg', images: [],
};

async function openAddons(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

function scenePackRequestCount(mockServer) {
  return mockServer.requestLog.filter((r) => r.startsWith('GET /api/fraimic/scene_packs')).length;
}

test.describe('Add-ons catalog refresh', () => {
  test('switching to the Add-ons tab refetches a catalog that changed after init', async ({ page }) => {
    const scenePacks = [PACK_ONE];
    const mockServer = createMockServer({ scenePacks });
    const baseUrl = await mockServer.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [] });
      await openAddons(page);

      // Category-tile view first for scene packs -- open the "nature" tile
      // to reach the flat grid where pack titles are listed.
      await page.evaluate(() => {
        const root = document.getElementById('panel').shadowRoot;
        const tile = [...root.querySelectorAll('#art-categories-grid .category-tile')]
          .find((el) => el.querySelector('.category-tile-title').textContent.trim() === 'Nature');
        tile.click();
      });
      const titlesNow = () => page.evaluate(() =>
        [...document.getElementById('panel').shadowRoot.querySelectorAll('.scene-card-title')]
          .map((el) => el.textContent.trim()));

      expect(await titlesNow()).toEqual(['Pack One']);

      // The manifest changes upstream -- the mock server serves this array
      // live, same as the real GitHub-raw-content fetch would after a push.
      scenePacks.push(PACK_TWO);

      // Simulate more than the 10s throttle window having passed since
      // init's own load (this test isn't about the throttle -- that's
      // covered separately below).
      await page.evaluate(() => { document.getElementById('panel')._scenePacksLoadedAt = 0; });

      // Re-clicking the already-active Add-ons tab is exactly what a user
      // does when they think the panel "isn't loading" -- it must refetch.
      await openAddons(page);
      await page.waitForFunction(
        () => [...document.getElementById('panel').shadowRoot.querySelectorAll('.scene-card-title')]
          .some((el) => el.textContent.trim() === 'Pack Two'),
        { timeout: 5000 },
      );
      expect(await titlesNow()).toEqual(expect.arrayContaining(['Pack One', 'Pack Two']));
    } finally {
      await mockServer.stop();
    }
  });

  test('rapid tab re-activation is throttled -- no refetch storm from repeated clicks', async ({ page }) => {
    const scenePacks = [PACK_ONE];
    const mockServer = createMockServer({ scenePacks });
    const baseUrl = await mockServer.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [] });
      await openAddons(page);
      const afterFirstOpen = scenePackRequestCount(mockServer);

      // Immediately click again (and again) -- well within the 10s throttle.
      await openAddons(page);
      await openAddons(page);
      // Give any (incorrect) fire-and-forget fetch a moment to land.
      await page.waitForTimeout(200);

      expect(scenePackRequestCount(mockServer)).toBe(afterFirstOpen);
    } finally {
      await mockServer.stop();
    }
  });

  test('reattaching the panel element (_revive) also refetches a stale catalog', async ({ page }) => {
    const scenePacks = [PACK_ONE];
    const mockServer = createMockServer({ scenePacks });
    const baseUrl = await mockServer.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [] });

      // Force the throttle window closed without a real 10s wait.
      await page.evaluate(() => { document.getElementById('panel')._scenePacksLoadedAt = 0; });

      scenePacks.push(PACK_TWO);

      // Detach then reattach -- same lifecycle path as lifecycle.spec.js
      // uses for its revive coverage.
      await page.evaluate(() => { window.__panel = document.getElementById('panel'); });
      await page.evaluate(() => window.__panel.remove());
      await page.waitForTimeout(100); // let the dispose timer fire
      await page.evaluate(() => document.body.appendChild(window.__panel));

      await page.waitForFunction(() => document.getElementById('panel')._scenePacks.some((p) => p.id === 'pack_two'), { timeout: 5000 });
    } finally {
      await mockServer.stop();
    }
  });
});
