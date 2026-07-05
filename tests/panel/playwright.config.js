// @ts-check
const { defineConfig, devices } = require('@playwright/test');

// No shared webServer entry here: each spec's mock backend needs fresh
// per-test state (frames/scenes/walls reset between tests), so servers are
// started/stopped per test via fixtures/mock-server.js instead of one
// long-lived server for the whole run.
module.exports = defineConfig({
  testDir: '.',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
