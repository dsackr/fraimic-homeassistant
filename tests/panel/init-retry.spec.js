// Init-load resilience: a transient HA-restart/reconnect window (failing
// REST endpoints, a websocket that isn't ready) must not paint a
// believably-empty dashboard, show zero-state messaging, or trigger the
// onboarding tour. Loads retry with backoff; a load that never recovers
// leaves a visible "incomplete" note instead of a fake-empty install.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const SCENES = [{ scene_id: 'scene_1', name: 'Fall', mappings: { entry_1: 'img_1' } }];
const ALBUMS = [{ name: 'Vacation', count: 1, cover_image_id: 'img_1' }];

// Like fixtures/panel-page gotoPanel, but shortens the retry backoff (an
// instance field for exactly this purpose) before hass kicks off _init,
// and optionally patches the mock hass (e.g. a flaky callWS).
async function gotoPanelForRetry(page, baseUrl, frames, { patchHass = '' } = {}) {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err));
  await page.goto(`${baseUrl}/harness.html`);
  await page.evaluate(({ frameList, patch }) => {
    const panel = document.getElementById('panel');
    panel._initRetryDelays = [150, 150];
    const hass = window.__buildMockHass(frameList);
    if (patch) new Function('hass', patch)(hass);
    panel.hass = hass;
  }, { frameList: frames, patch: patchHass });
  await page.waitForFunction(() => document.getElementById('panel')._loaded, { timeout: 10000 });
  return { pageErrors };
}

function initState(page) {
  return page.evaluate(() => {
    const panel = document.getElementById('panel');
    const fb = panel.shadowRoot.getElementById('wall-fb');
    return {
      frames: panel._frames.length,
      frameWidth: panel._frames.length ? panel._frames[0].width : null,
      scenes: panel._scenes.length,
      walls: panel._walls.length,
      albums: panel._albums.length,
      errors: [...panel._initLoadErrors].sort(),
      retriesActive: panel._initRetriesActive,
      note: fb.style.display === 'block' ? fb.textContent : null,
      onboardingOpen: panel.shadowRoot.getElementById('onboarding-overlay').style.display === 'flex',
    };
  });
}

test.describe('Init load retry and zero-state suppression', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('a transient outage recovers by itself — no refresh needed', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, albums: ALBUMS,
      failing: true,
    });
    baseUrl = await mockServer.start();

    // Heal the "restarting" backend shortly after the panel starts loading.
    setTimeout(() => mockServer.setFailing(false), 250);
    await gotoPanelForRetry(page, baseUrl, FRAMES);

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._scenes.length === 1
        && panel._walls.length >= 1
        && panel._albums.length === 1
        && panel._initLoadErrors.size === 0
        && panel._initRetriesActive === 0;
    }, { timeout: 10000 });

    const state = await initState(page);
    // The retried REST enrichment landed too (width comes from /frames).
    expect(state.frameWidth).toBe(1200);
    // No leftover reconnecting/incomplete note.
    expect(state.note).toBe(null);
  });

  test('a persistent outage shows the incomplete note and never opens the tour', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, albums: ALBUMS,
      failing: true,
      onboardingComplete: false, // would open the tour if emptiness were believed
    });
    baseUrl = await mockServer.start();
    await gotoPanelForRetry(page, baseUrl, FRAMES);

    // Wait for every dashboard load to exhaust its retries.
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._initLoadErrors.size >= 5 && panel._initRetriesActive === 0;
    }, { timeout: 10000 });
    await page.waitForTimeout(500); // _maybeOpenOnboarding has long since run

    const state = await initState(page);
    expect(state.note).toContain("Couldn't load everything");
    expect(state.onboardingOpen).toBe(false);
    // Scenes/walls read empty, but the panel knows they're UNKNOWN.
    expect(state.errors).toContain('scenes');
    expect(state.errors).toContain('walls');
  });

  test('a broken onboarding flag endpoint fails closed, even with a JSON body', async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES, scenes: SCENES, albums: ALBUMS,
      onboardingComplete: false,
      onboardingBroken: true, // 500 + JSON body with no `complete` field
    });
    baseUrl = await mockServer.start();
    await gotoPanelForRetry(page, baseUrl, FRAMES);

    await page.waitForFunction(
      () => document.getElementById('panel')._initRetriesActive === 0
        && document.getElementById('panel')._scenes.length === 1,
      { timeout: 10000 }
    );
    await page.waitForTimeout(500);

    const state = await initState(page);
    expect(state.onboardingOpen).toBe(false);
    expect(state.errors).toEqual([]); // everything else loaded fine
  });

  test('a websocket that is not ready yet retries frame discovery', async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, scenes: SCENES, albums: ALBUMS });
    baseUrl = await mockServer.start();

    // config_entries/get rejects twice (HA still starting), then recovers.
    await gotoPanelForRetry(page, baseUrl, FRAMES, {
      patchHass: `
        const orig = hass.callWS.bind(hass);
        let failures = 2;
        hass.callWS = (msg) => {
          if (msg.type === 'config_entries/get' && failures > 0) {
            failures--;
            return Promise.reject(new Error('Home Assistant is starting'));
          }
          return orig(msg);
        };
      `,
    });

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._frames.length === 1 && panel._initLoadErrors.size === 0;
    }, { timeout: 10000 });

    const state = await initState(page);
    expect(state.frames).toBe(1);
    expect(state.note).toBe(null);
  });

  test('non-admins never see "ask your administrator" from an errored load', async ({ page }) => {
    mockServer = createMockServer({ frames: [], failing: true, onboardingComplete: false });
    baseUrl = await mockServer.start();
    await gotoPanelForRetry(page, baseUrl, [], {
      patchHass: 'hass.user.is_admin = false;',
    });

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._initLoadErrors.size >= 1 && panel._initRetriesActive === 0;
    }, { timeout: 10000 });
    await page.waitForTimeout(500);

    const state = await initState(page);
    expect(state.note).toContain("Couldn't load everything");
    expect(state.note).not.toContain('administrator');
    expect(state.onboardingOpen).toBe(false);
  });
});
