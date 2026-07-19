// KPF 33 — dismissable "new version available" dashboard banner.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const FRAMES = [{ entry_id: 'entry_1', title: 'Kitchen' }];

async function bannerState(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    const banner = root.getElementById('update-banner');
    return {
      display: banner ? banner.style.display : null,
      text: banner ? banner.textContent : '',
      hasInstall: !!(banner && root.getElementById('update-banner-install')),
      hasDismiss: !!(banner && root.getElementById('update-banner-dismiss')),
    };
  });
}

test.describe('Update available banner', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    if (mockServer) await mockServer.stop();
  });

  test('shows when update_available and banner_visible', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      updateStatus: {
        installed: '0.12.100',
        disk: '0.12.100',
        running: '0.12.100',
        latest: '0.12.120',
        latest_tag: 'v0.12.120',
        update_available: true,
        banner_visible: true,
      },
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await expect.poll(async () => (await bannerState(page)).display).toBe('flex');
    const state = await bannerState(page);
    expect(state.text).toContain('v0.12.120');
    expect(state.text).toContain('v0.12.100');
    expect(state.hasInstall).toBe(true);
    expect(state.hasDismiss).toBe(true);
  });

  test('hidden when up to date', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.waitForTimeout(300);
    const state = await bannerState(page);
    expect(state.display).toBe('none');
  });

  test('Dismiss hides the banner and POSTs the version', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      updateStatus: {
        installed: '0.12.100',
        disk: '0.12.100',
        running: '0.12.100',
        latest: '0.12.120',
        update_available: true,
        banner_visible: true,
      },
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await expect.poll(async () => (await bannerState(page)).display).toBe('flex');

    await clickPanelButton(page, 'update-banner-dismiss');
    await expect.poll(async () => (await bannerState(page)).display).toBe('none');
    await expect.poll(() => mockServer.updateDismisses.length).toBe(1);
    expect(mockServer.updateDismisses[0].version).toBe('0.12.120');
  });

  test('non-admins never see the banner', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      updateStatus: {
        installed: '0.12.100',
        latest: '0.12.120',
        update_available: true,
        banner_visible: true,
      },
    });
    baseUrl = await mockServer.start();
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

    await page.waitForTimeout(400);
    const state = await bannerState(page);
    expect(state.display).toBe('none');
  });
});
