// Coverage for the embedded config/options flow renderer: the generic
// data_entry_flow step renderer that drives HA's own flow API from inside
// the panel (add frame, reconfigure) -- field rendering for every serialized
// type our schemas produce, submit payload shapes, error display, and the
// cancel-deletes-user-flows / cancel-preserves-discovered-flows contract.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];

function flowModalState(page) {
  return page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    const overlay = root.getElementById('flow-modal-overlay');
    const body = root.getElementById('flow-modal-body');
    return {
      open: overlay.style.display === 'flex',
      title: root.getElementById('flow-modal-title').textContent,
      fields: [...body.querySelectorAll('[data-flow-field]')].map((el) => ({
        name: el.dataset.flowField,
        type: el.dataset.flowType,
        tag: el.tagName.toLowerCase(),
        inputType: el.type || null,
        value: el.type === 'checkbox' ? el.checked : el.value,
        min: el.min || null,
        options: el.tagName === 'SELECT' ? [...el.options].map((o) => o.value) : null,
      })),
      fieldErrors: [...body.querySelectorAll('.flow-field-error')].map((el) => el.textContent),
      fb: root.getElementById('flow-modal-fb').textContent,
      submitVisible: root.getElementById('flow-modal-submit').style.display !== 'none',
    };
  });
}

async function setFlowField(page, name, value) {
  await page.evaluate(({ name, value }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(`flow-field-${name}`);
    if (el.type === 'checkbox') el.checked = value;
    else el.value = value;
  }, { name, value });
}

async function waitForStep(page, stepId) {
  await page.waitForFunction((id) => {
    const panel = document.getElementById('panel');
    return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === id;
  }, stepId, { timeout: 5000 });
}

test.describe('Embedded flow renderer', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Add Frame drives user → pick_device → name_device → create_entry with correct payloads', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });

    await clickPanelButton(page, 'frame-add-btn');
    await waitForStep(page, 'user');

    let state = await flowModalState(page);
    expect(state.fields).toEqual([
      expect.objectContaining({ name: 'host', type: 'string', inputType: 'text', value: '' }),
    ]);

    // Empty host = "scan my network" -- must be submitted as "".
    await clickPanelButton(page, 'flow-modal-submit');
    await waitForStep(page, 'pick_device');
    expect(mockServer.flowSubmissions[0].body).toEqual({ host: '' });

    state = await flowModalState(page);
    expect(state.fields[0]).toEqual(expect.objectContaining({
      name: 'device', type: 'select', tag: 'select',
      options: ['192.168.1.31', '192.168.1.35', '__manual__'],
    }));

    await setFlowField(page, 'device', '192.168.1.35');
    await clickPanelButton(page, 'flow-modal-submit');
    await waitForStep(page, 'name_device');
    expect(mockServer.flowSubmissions[1].body).toEqual({ device: '192.168.1.35' });

    await setFlowField(page, 'name', 'Hallway Frame');
    await clickPanelButton(page, 'flow-modal-submit');
    await page.waitForFunction(() => !document.getElementById('panel')._flowModal, { timeout: 5000 });
    expect(mockServer.flowSubmissions[2].body).toEqual({ name: 'Hallway Frame' });

    // create_entry closes the modal without DELETEing the finished flow.
    expect(mockServer.flowDeletes).toEqual([]);
    expect(pageErrors).toEqual([]);
  });

  test('the picker offers a manual-IP escape hatch that leads to naming', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await clickPanelButton(page, 'frame-add-btn');
    await waitForStep(page, 'user');
    await clickPanelButton(page, 'flow-modal-submit');   // empty host → picker
    await waitForStep(page, 'pick_device');

    await setFlowField(page, 'device', '__manual__');
    await clickPanelButton(page, 'flow-modal-submit');
    await waitForStep(page, 'manual');

    await setFlowField(page, 'host', '10.9.8.7');
    await clickPanelButton(page, 'flow-modal-submit');
    await waitForStep(page, 'name_device');
  });

  test('a failing host shows the per-field error and keeps the form usable', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await clickPanelButton(page, 'frame-add-btn');
    await waitForStep(page, 'user');
    await setFlowField(page, 'host', '10.0.0.99');
    await clickPanelButton(page, 'flow-modal-submit');

    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelectorAll('.flow-field-error').length > 0;
    }, { timeout: 5000 });

    const state = await flowModalState(page);
    // No translations in the harness -- raw error code is the documented
    // fallback.
    expect(state.fieldErrors).toEqual(['cannot_connect']);
    expect(state.submitVisible).toBe(true);
  });

  test('Enter in a form field submits the step like the button does', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await clickPanelButton(page, 'frame-add-btn');
    await waitForStep(page, 'user');

    await page.evaluate(() => {
      const el = document.getElementById('panel').shadowRoot.getElementById('flow-field-host');
      el.focus();
      el.value = '192.168.1.31';
    });
    await page.keyboard.press('Enter');

    await waitForStep(page, 'name_device');
    expect(mockServer.flowSubmissions[0].body).toEqual({ host: '192.168.1.31' });
  });

  test('cancelling a user-initiated flow DELETEs it server-side', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await clickPanelButton(page, 'frame-add-btn');
    await waitForStep(page, 'user');
    await clickPanelButton(page, 'flow-modal-cancel');

    await expect.poll(() => mockServer.flowDeletes.length).toBe(1);
  });

  test('the options flow renders integer/select/boolean fields and submits typed values', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.evaluate(() => {
      const panel = document.getElementById('panel');
      panel._openFlowModal({
        title: 'Configure',
        base: '/api/config/config_entries/options/flow',
        start: () => panel._startOptionsFlow('entry_1'),
        userInitiated: true,
      });
    });
    await waitForStep(page, 'init');

    const state = await flowModalState(page);
    expect(state.fields).toEqual([
      expect.objectContaining({ name: 'scan_interval', type: 'integer', inputType: 'number', value: '300', min: '30' }),
      expect.objectContaining({ name: 'rotation_edge', type: 'select', value: 'left' }),
      expect.objectContaining({ name: 'rotate_portrait_180', type: 'boolean', inputType: 'checkbox', value: false }),
      expect.objectContaining({ name: 'rotate_landscape_180', type: 'boolean', value: false }),
    ]);

    await setFlowField(page, 'scan_interval', '120');
    await setFlowField(page, 'rotation_edge', 'right');
    await setFlowField(page, 'rotate_portrait_180', true);
    await clickPanelButton(page, 'flow-modal-submit');
    await page.waitForFunction(() => !document.getElementById('panel')._flowModal, { timeout: 5000 });

    // Types must survive collection: integer as number, booleans as booleans.
    expect(mockServer.flowSubmissions[0].body).toEqual({
      scan_interval: 120,
      rotation_edge: 'right',
      rotate_portrait_180: true,
      rotate_landscape_180: false,
    });
  });
});
