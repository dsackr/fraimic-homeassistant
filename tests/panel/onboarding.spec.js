// Coverage for the first-run onboarding wizard: a 6-step tour that opens
// for admins until the server-side flag (/api/fraimic/onboarding) is set.
// Step 2 embeds the real Add-Frame flow (manual and discovered paths),
// step 5 mounts the real storage-backend picker inline, and completing or
// skipping anywhere sets the flag install-wide so it never reopens.

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
      body: root.getElementById('onboarding-body').textContent,
      skipVisible: root.getElementById('onboarding-skip').style.display !== 'none',
      activeDots: root.querySelectorAll('.ob-dot.active').length,
    };
  });
}

// The wizard opens async (it awaits the flag fetch after panel._loaded).
async function waitForWizard(page) {
  await page.waitForFunction(() => {
    const panel = document.getElementById('panel');
    return panel._onboarding
      && panel.shadowRoot.getElementById('onboarding-overlay').style.display === 'flex';
  }, { timeout: 5000 });
}

async function waitForStep(page, step) {
  await page.waitForFunction(
    (s) => {
      const panel = document.getElementById('panel');
      return panel._onboarding && panel._onboarding.step === s;
    },
    step,
    { timeout: 5000 }
  );
}

test.describe('First-run onboarding', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: [],
      discoveredFlows: [{ flow_id: 'flow_disc1', host: '192.168.1.31' }],
      onboardingComplete: false,
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('walks all six steps, adding a frame on the way', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: [] });
    await waitForWizard(page);

    // Step 1 (Welcome): no header Skip -- its own ghost button is the exit.
    let state = await wizardState(page);
    expect(state.step).toBe(1);
    expect(state.body).toContain('Fraimic');
    expect(state.skipVisible).toBe(false);
    expect(state.activeDots).toBe(1);
    await clickPanelButton(page, 'ob-next');

    // Step 2 (Frames): the embedded Add-Frame flow stacks above the wizard.
    state = await wizardState(page);
    expect(state.step).toBe(2);
    expect(state.body).toContain('Discover your frames');
    expect(state.skipVisible).toBe(true);
    await clickPanelButton(page, 'onboarding-add-btn');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'user';
    }, { timeout: 5000 });
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('flow-field-host').value = '192.168.1.35';
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

    // create_entry surfaces on the step (the wizard stays on Frames).
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._onboarding && panel._onboarding.framesAdded === 1;
    }, { timeout: 5000 });
    state = await wizardState(page);
    expect(state.step).toBe(2);
    expect(state.body).toContain('Frame added');
    await clickPanelButton(page, 'ob-next');

    // Steps 3 (Walls) and 4 (Scenes) are explanatory.
    state = await wizardState(page);
    expect(state.step).toBe(3);
    expect(state.body).toContain('Organize your frames');
    await clickPanelButton(page, 'ob-next');
    state = await wizardState(page);
    expect(state.step).toBe(4);
    expect(state.body).toContain('Voice-controlled displays');
    await clickPanelButton(page, 'ob-next');

    // Step 5 (Storage): Local is the active backend, so Save & Continue
    // advances without touching anything.
    state = await wizardState(page);
    expect(state.step).toBe(5);
    expect(state.body).toContain('Where should photos live');
    expect(state.body).toContain('Using local storage');
    await clickPanelButton(page, 'ob-storage-continue');
    await waitForStep(page, 6);

    // Step 6 (Done): finishing closes the wizard and sets the server flag.
    state = await wizardState(page);
    expect(state.body).toContain("You're all set");
    expect(state.skipVisible).toBe(false);
    expect(state.activeDots).toBe(6);
    await clickPanelButton(page, 'ob-finish');
    expect((await wizardState(page)).open).toBe(false);
    await expect.poll(() => mockServer.onboardingComplete).toBe(true);
    expect(pageErrors).toEqual([]);
  });

  test('the Frames step lists frames the background scan already discovered', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: [] });
    await waitForWizard(page);
    await clickPanelButton(page, 'ob-next');

    await page.waitForFunction(() => {
      const body = document.getElementById('panel').shadowRoot.getElementById('onboarding-discovered');
      return body && body.textContent.includes('192.168.1.31');
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

  test('the storage step blocks Drive/Dropbox until connected, then connects Dropbox inline', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: [] });
    await waitForWizard(page);
    for (const _ of [2, 3, 4, 5]) await clickPanelButton(page, 'ob-next');
    expect((await wizardState(page)).step).toBe(5);

    // Selecting Dropbox mounts its inline token form; Continue without
    // connecting stays put with a pointer.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot
        .querySelector('.ob-storage-row[data-backend="dropbox"]').click();
    });
    let state = await wizardState(page);
    expect(state.body).toContain('access token');
    await clickPanelButton(page, 'ob-storage-continue');
    state = await wizardState(page);
    expect(state.step).toBe(5);
    expect(state.body).toContain('Finish connecting above first');

    // The inline connect is the real backend switch.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('dropbox-token').value = 'tok_test';
    });
    await clickPanelButton(page, 'dropbox-connect');
    await page.waitForFunction(
      () => document.getElementById('panel')._backend === 'dropbox',
      { timeout: 5000 }
    );
    expect(mockServer.libraryBackend).toBe('dropbox');
    expect((await wizardState(page)).body).toContain('Connected to Dropbox');
    await clickPanelButton(page, 'ob-storage-continue');
    await waitForStep(page, 6);
  });

  test('"I already know my way around" and "Skip →" both retire the wizard install-wide', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: [] });
    await waitForWizard(page);

    await clickPanelButton(page, 'ob-exit');
    expect((await wizardState(page)).open).toBe(false);
    await expect.poll(() => mockServer.onboardingComplete).toBe(true);

    // Re-running the trigger respects the (now server-side) flag.
    await page.evaluate(() => document.getElementById('panel')._maybeOpenOnboarding());
    await page.waitForTimeout(200);
    expect((await wizardState(page)).open).toBe(false);
  });

  test('"Skip →" mid-tour sets the flag too', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: [] });
    await waitForWizard(page);
    await clickPanelButton(page, 'ob-next');
    await clickPanelButton(page, 'ob-next');
    expect((await wizardState(page)).step).toBe(3);

    await clickPanelButton(page, 'onboarding-skip');
    expect((await wizardState(page)).open).toBe(false);
    await expect.poll(() => mockServer.onboardingComplete).toBe(true);
  });

  test('a completed flag keeps the wizard closed, even at zero frames', async ({ page }) => {
    const completedServer = createMockServer({ frames: [] });
    const completedUrl = await completedServer.start();
    try {
      const { pageErrors } = await gotoPanel(page, completedUrl, { frames: [] });
      await expect.poll(
        () => completedServer.requestLog.some((r) => r === 'GET /api/fraimic/onboarding')
      ).toBe(true);
      expect((await wizardState(page)).open).toBe(false);
      expect(pageErrors).toEqual([]);
    } finally {
      await completedServer.stop();
    }
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
