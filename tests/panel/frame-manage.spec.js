// Coverage for embedded frame management (the per-card gear menu) and the
// discovered-frames banner: rename via config_entries/update, remove via
// the config entry DELETE endpoint, banner rendering from flow-subscribe
// events, resuming a discovered flow without deleting it on cancel, and
// admin gating of all of the above.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'auto' },
];

const DISCOVERED_FLOW = {
  flow_id: 'flow_disc1',
  handler: 'fraimic',
  context: { source: 'integration_discovery', title_placeholders: { name: '192.168.1.31' } },
  step_id: 'name_device',
};

async function openGearFor(page, entryId) {
  // The manage gear lives on the frame's wall-tile footer (every frame is
  // placed on the default wall).
  await page.waitForFunction((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    return tile && tile.querySelector('.wall-tile-gear');
  }, entryId, { timeout: 5000 });
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    tile.querySelector('.wall-tile-gear').click();
  }, entryId);
}

test.describe('Frame management and discovery banner', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      discoveredFlows: [{ flow_id: 'flow_disc1', host: '192.168.1.31' }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('gear → rename issues config_entries/update with the new title', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openGearFor(page, 'entry_1');
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-settings-name').value = 'Kitchen Frame';
    });
    await clickPanelButton(page, 'frame-settings-rename');

    // Both registries must be updated: entry title alone leaves the device
    // page showing the creation-time name.
    await expect.poll(() => page.evaluate(
      () => window.__wsCalls.filter((c) => c.type === 'config_entries/update' || c.type === 'config/device_registry/update')
    )).toEqual([
      { type: 'config_entries/update', entry_id: 'entry_1', title: 'Kitchen Frame' },
      { type: 'config/device_registry/update', device_id: 'entry_1', name_by_user: 'Kitchen Frame' },
    ]);
  });

  test('gear → remove confirms then DELETEs the config entry', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openGearFor(page, 'entry_2');
    page.once('dialog', (dialog) => dialog.accept());
    await clickPanelButton(page, 'frame-settings-remove');

    await expect.poll(() => mockServer.entryDeletes).toEqual(['entry_2']);
  });

  test('gear → configure opens the options flow for that entry', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openGearFor(page, 'entry_1');
    await clickPanelButton(page, 'frame-settings-configure');

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'init';
    }, { timeout: 5000 });
    // The options flow was started against the right entry.
    expect(mockServer.requestLog).toContain('POST /api/config/config_entries/options/flow');
  });

  test('the banner renders discovered flows and its Add resumes that flow_id', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'flex';
    }, { timeout: 5000 });

    const bannerText = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('discovery-banner').textContent
    );
    expect(bannerText).toContain('1 frame found');
    expect(bannerText).toContain('192.168.1.31');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.banner-add-btn').click();
    });
    // Resuming = GET on the pending flow, landing straight on name_device.
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'name_device';
    }, { timeout: 5000 });
    expect(mockServer.requestLog).toContain('GET /api/config/config_entries/flow/flow_disc1');

    // Cancelling a discovered flow must NOT delete it server-side -- it has
    // to stay pending for HA's own Discovered card.
    await clickPanelButton(page, 'flow-modal-cancel');
    await page.waitForTimeout(200);
    expect(mockServer.flowDeletes).toEqual([]);
  });

  test('a flow-subscribe removal event clears the banner', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'flex';
    }, { timeout: 5000 });

    await page.evaluate(() => {
      window.__flowSubCallback([{ type: 'removed', flow_id: 'flow_disc1' }]);
    });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'none';
    }, { timeout: 5000 });
  });

  test('non-admins see no Add button, gear buttons, or banner', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err));

    await page.goto(`${baseUrl}/harness.html`);
    await page.evaluate((frameList) => {
      const hass = window.__buildMockHass(frameList);
      hass.user = { is_admin: false };
      document.getElementById('panel').hass = hass;
    }, FRAMES);
    await page.waitForFunction(
      (n) => {
        const panel = document.getElementById('panel');
        return panel && panel._frames && panel._frames.length === n && panel._loaded;
      },
      FRAMES.length,
      { timeout: 10000 }
    );

    const visibility = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        addBtn: root.getElementById('frame-add-btn').style.display,
        // Non-admin tiles are rendered without a gear at all.
        gearCount: root.querySelectorAll('.wall-tile-gear').length,
        tileCount: root.querySelectorAll('.wall-tile').length,
        banner: root.getElementById('discovery-banner').style.display,
      };
    });
    expect(visibility.addBtn).toBe('none');
    expect(visibility.tileCount).toBe(2);
    expect(visibility.gearCount).toBe(0);
    expect(visibility.banner).toBe('none');
    expect(pageErrors).toEqual([]);
  });
});
