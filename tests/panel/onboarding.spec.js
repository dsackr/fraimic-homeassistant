// Coverage for the first-run onboarding wizard: auto-opens at zero frames
// (admins only), step 1 drives the embedded Add-Frame flow (manual and
// discovered paths), completing an add advances to the storage step,
// finishing lands on the dashboard, and "Set up later" dismisses
// persistently until frames exist again.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const DISCOVERED_FLOW = {
  flow_id: 'flow_disc1',
  handler: 'fraimic',
  context: { source: 'integration_discovery', title_placeholders: { name: '192.168.1.31' } },
  step_id: 'name_device',
};

function wizardState(page) {
  return page.evaluate(() => {
    const panel = document.getElementById('panel');
    const root = panel.shadowRoot;
    return {
      open: root.getElementById('onboarding-overlay').style.display === 'flex',
      step: panel._onboarding ? panel._onboarding.step : null,
      title: root.getElementById('onboarding-title').textContent,
    };
  });
}

test.describe('First-run onboarding', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: [],
      discoveredFlows: [{ flow_id: 'flow_disc1', host: '192.168.1.31' }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('auto-opens at zero frames and walks add → storage → done', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: [] });

    expect(await wizardState(page)).toEqual({
      open: true, step: 1, title: 'Welcome to Fraimic 👋',
    });

    // Step 1: the embedded Add-Frame flow stacks above the wizard.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('onboarding-add-btn').click();
    });
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'user';
    }, { timeout: 5000 });

    await page.evaluate(() => {
      const el = document.getElementById('panel').shadowRoot.getElementById('flow-field-host');
      el.value = '192.168.1.35';
    });
    await clickPanelButton(page, 'flow-modal-submit');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'name_device';
    }, { timeout: 5000 });
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('flow-field-name').value = 'First Frame';
    });
    await clickPanelButton(page, 'flow-modal-submit');

    // create_entry advances the wizard to the storage step.
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._onboarding && panel._onboarding.step === 2;
    }, { timeout: 5000 });
    expect((await wizardState(page)).title).toContain('Frame added');

    // "Choose photo storage…" opens the Settings modal on top.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('onboarding-storage-btn').click();
    });
    expect(await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('settings-modal-overlay').style.display
    )).toBe('flex');
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('settings-modal-close').click();
    });

    // Finish → wizard gone, dashboard is what remains.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('onboarding-finish').click();
    });
    expect((await wizardState(page)).open).toBe(false);
    expect(pageErrors).toEqual([]);
  });

  test('step 1 lists frames the background scan already discovered', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: [] });

    await page.waitForFunction(() => {
      const body = document.getElementById('panel').shadowRoot.getElementById('onboarding-body');
      return body.textContent.includes('192.168.1.31');
    }, { timeout: 5000 });

    // Its add button resumes the pending flow at the naming step.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot
        .querySelector('#onboarding-discovered .banner-add-btn').click();
    });
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'name_device';
    }, { timeout: 5000 });
  });

  test('"Set up later" dismisses persistently while frames remain zero', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: [] });
    expect((await wizardState(page)).open).toBe(true);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('onboarding-skip').click();
    });
    expect((await wizardState(page)).open).toBe(false);
    expect(await page.evaluate(() => localStorage.getItem('fraimic_onboarding_dismissed'))).toBe('1');

    // Re-running the trigger respects the dismissal…
    await page.evaluate(() => document.getElementById('panel')._maybeOpenOnboarding());
    expect((await wizardState(page)).open).toBe(false);

    // …and the flag clears itself once frames exist, so a future return
    // to zero frames re-offers the wizard.
    await page.evaluate(() => {
      const panel = document.getElementById('panel');
      panel._frames = [{ entryId: 'entry_1', title: 'X' }];
      panel._maybeOpenOnboarding();
    });
    expect(await page.evaluate(() => localStorage.getItem('fraimic_onboarding_dismissed'))).toBe(null);
  });

  test('non-admins get a pointer, not the wizard', async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err));
    await page.goto(`${baseUrl}/harness.html`);
    await page.evaluate(() => {
      const hass = window.__buildMockHass([]);
      hass.user = { is_admin: false };
      document.getElementById('panel').hass = hass;
    });
    await page.waitForFunction(
      () => document.getElementById('panel')._loaded, { timeout: 10000 }
    );

    expect((await wizardState(page)).open).toBe(false);
    const fb = await page.evaluate(() => {
      const el = document.getElementById('panel').shadowRoot.getElementById('wall-fb');
      return { text: el.textContent, display: el.style.display };
    });
    expect(fb.display).toBe('block');
    expect(fb.text).toContain('administrator');
    expect(pageErrors).toEqual([]);
  });
});
