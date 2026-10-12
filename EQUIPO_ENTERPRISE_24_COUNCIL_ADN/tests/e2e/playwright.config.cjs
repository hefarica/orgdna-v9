'use strict';
const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: '*.spec.cjs',
  timeout: 45000,
  expect: { timeout: 12000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir: 'artifacts/test-results',
  reporter: [['line'], ['html', { outputFolder: 'artifacts/html', open: 'never' }],
             ['json', { outputFile: 'artifacts/results.json' }]],
  use: {
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    locale: 'es-ES',
    timezoneId: 'UTC',
    acceptDownloads: true,
    serviceWorkers: 'block',
    trace: 'on',
    screenshot: 'on',
    video: 'retain-on-failure',
    actionTimeout: 12000
  }
});
