'use strict';
const { test: base, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const SENTINEL = 'E2E_SYNTHETIC_NONCREDENTIAL_NEVER_A_REAL_KEY';
const PAGES = ['inicio','organigrama','perfiles','council','habilidades','modelos','repositorio','exportaciones','registro'];

function startFixture() {
  return new Promise((resolve, reject) => {
    // No supplied base URL, existing instance discovery, shell or port argument.
    const python = process.env.ORGDNA_E2E_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const proc = spawn(python, ['-u', path.join(__dirname, 'fixture_server.py')], {
      cwd: __dirname, shell: false, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' }
    });
    let out = '', err = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('Fixture readiness timed out: ' + err)); }, 20000);
    proc.stderr.on('data', b => { err += b.toString(); });
    proc.once('error', error => { clearTimeout(timer); reject(error); });
    proc.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${err}`)); });
    proc.stdout.on('data', b => {
      out += b.toString();
      if (!out.includes('\n')) return;
      try {
        const value = JSON.parse(out.split('\n')[0]);
        if (!value.fixture || !/^http:\/\/127\.0\.0\.1:\d+$/.test(value.origin)) throw new Error('Unsafe fixture origin');
        clearTimeout(timer); resolve({ proc, origin: value.origin });
      } catch (error) { clearTimeout(timer); proc.kill(); reject(error); }
    });
  });
}

const test = base.extend({
  isolatedServer: [async ({}, use) => {
    const server = await startFixture();
    try { await use(server); }
    finally {
      if (server.proc.exitCode === null) {
        const exited = new Promise(resolve => server.proc.once('exit', resolve));
        server.proc.kill();
        await exited;
      }
    }
  }, { scope: 'worker' }],
  app: async ({ page, context, isolatedServer }, use, testInfo) => {
    const { origin } = isolatedServer;
    const errors = [], external = [], requests = [], expectedHttpErrors = [];
    const observePage = observed => {
      observed.on('pageerror', error => errors.push(error.message));
      observed.on('console', message => {
        if (message.type() !== 'error') return;
        const text = message.text(), url = message.location().url;
        const expected = expectedHttpErrors.find(item => item.active && item.url === url &&
          /^Failed to load resource: the server responded with a status of 400\b/.test(text));
        if (expected) expected.console.push({ text, url });
        else errors.push(text);
      });
    };
    for (const existing of context.pages()) observePage(existing);
    context.on('page', observePage);
    context.on('request', request => {
      if (request.method() === 'POST') requests.push(new URL(request.url()).pathname);
    });
    // Context routing also guards a popup's first request, unlike page routing.
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) {
        external.push(url.origin + url.pathname);
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    await page.goto(origin);
    await expect(page.locator('#notice')).not.toContainText('Conectando');
    const control = async (operation, body = {}) => {
      const token = await page.locator('meta[name="csrf-token"]').getAttribute('content');
      const response = await page.request.post(origin + '/__e2e__/' + operation, {
        headers: { 'Origin': origin, 'X-CSRF-Token': token }, data: body
      });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    };
    const state = async () => {
      const response = await page.request.get(origin + '/api/state');
      expect(response.ok()).toBeTruthy(); return response.json();
    };
    const expectActionError = async (actionPath, callback, pattern) => {
      if (!/^\/api\/[a-z-]+$/.test(actionPath) || !(pattern instanceof RegExp)) throw new Error('Exact action path and error regex required');
      const record = { url: origin + actionPath, active: true, verified: false, console: [] };
      expectedHttpErrors.push(record);
      try {
        const responsePending = page.waitForResponse(response => response.url() === record.url && response.request().method() === 'POST');
        await callback();
        const response = await responsePending;
        expect(response.status()).toBe(400);
        const body = await response.json();
        expect(body.error).toMatch(pattern);
        await expect(page.locator('#notice')).toContainText(pattern);
        record.verified = true;
        return body;
      } finally { record.active = false; }
    };
    await control('reset', {});
    await page.reload();
    await expect(page.locator('#stat-agents')).toHaveText('4');
    const navigate = async target => {
      await page.locator(`nav a[data-page="${target}"]`).click();
      await expect(page.locator('#' + target)).toBeVisible();
      await expect(page.locator('.page:not([hidden])')).toHaveCount(1);
    };
    const download = async locator => {
      const pending = page.waitForEvent('download');
      await locator.click();
      const file = await pending;
      expect(await file.failure()).toBeNull();
      const destination = testInfo.outputPath(file.suggestedFilename());
      await file.saveAs(destination);
      const bytes = await fs.readFile(destination);
      await testInfo.attach(file.suggestedFilename(), { path: destination,
        contentType: file.suggestedFilename().endsWith('.zip') ? 'application/zip' : 'application/json' });
      return { bytes, filename: file.suggestedFilename(), sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
        json: () => JSON.parse(bytes.toString('utf8')) };
    };
    try { await use({ page, origin, control, state, navigate, download, errors, requests, expectActionError }); }
    finally {
      const current = await state();
      await testInfo.attach('fixture-observations.json', { body: JSON.stringify(current.e2e_fixture, null, 2), contentType: 'application/json' });
      await testInfo.attach('browser-console.json', { body: JSON.stringify(errors, null, 2), contentType: 'application/json' });
      await testInfo.attach('expected-http-errors.json', { body: JSON.stringify(expectedHttpErrors, null, 2), contentType: 'application/json' });
      for (const expected of expectedHttpErrors) {
        expect(expected.verified, 'An expected rejection must be asserted by status, body and UI feedback').toBe(true);
        expect(expected.console.length, 'At most one exact HTTP400 resource message is expected per rejection').toBeLessThanOrEqual(1);
      }
      expect(current.e2e_fixture.live_provider_calls).toBe(0);
      expect(current.e2e_fixture.blocked_actions, 'Unexpected action reached the fixture safety guard').toEqual([]);
      expect(external, 'Browser attempted external traffic').toEqual([]);
      expect(errors, 'Browser console or JavaScript error').toEqual([]);
    }
  }
});

async function prepare(app, mode = 'success') {
  await app.navigate('inicio');
  await app.control('mode', { mode });
  await app.page.locator('#prepare-generation').click();
  await expect(app.page.locator('#generation-preview')).toBeVisible();
  await expect(app.page.locator('#generation-consent')).not.toBeChecked();
  await expect(app.page.locator('#confirm-generation')).toBeDisabled();
}
async function approve(app) {
  await app.page.locator('#generation-consent').check();
  await app.page.locator('#confirm-generation').click();
}
async function waitJob(app, status) {
  await expect.poll(async () => (await app.state()).generation_job?.status).toBe(status);
  await expect(app.page.locator('#generation-preview')).toBeHidden();
  await expect(app.page.locator('#generation-result')).toBeVisible();
  await expect(app.page.locator('#generation-progress')).toBeVisible();
}
async function acceptNextDialog(page, callback) {
  page.once('dialog', dialog => dialog.accept()); await callback();
}
async function openDetailsFor(page, selector) {
  // Read ancestor state, then open through actual pointer controls, outer first.
  const details = page.locator('details').filter({ has: page.locator(selector) });
  for (const ancestor of await details.all()) {
    if (await ancestor.getAttribute('open') === null) await ancestor.locator(':scope > summary').click();
  }
}
module.exports = { test, expect, SENTINEL, PAGES, prepare, approve, waitJob, acceptNextDialog, openDetailsFor };
