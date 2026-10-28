// Render the production secure form in Chromium without a real credential or account.
import { createRequire } from 'node:module';
import { writeFile, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '../../../apps/desktop');
const require = createRequire(join(desktop, 'package.json'));
const { chromium } = require('@playwright/test');
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
const name = `.browser-auth-ui-${randomUUID()}.html`;
const file = join(desktop, name);
let server;
let browser;
try {
  await writeFile(file, `<!doctype html><html><body><div id="root"></div><script type="module">
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {Theme} from '@radix-ui/themes';
    import {I18nProvider} from '/src/i18n.tsx';
    import {BrowserAuthRequests} from '/src/features/chat/BrowserAuthRequests.tsx';
    const config={mode:'local',apiBaseUrl:location.origin,apiKey:'test-only',localApiToken:'test-only',tenantId:'test',projectId:'test',workspaceId:'test',workspaceRoot:'',deviceAuthorizationBaseUrl:''};
    createRoot(document.getElementById('root')).render(React.createElement(I18nProvider,null,React.createElement(Theme,null,React.createElement(BrowserAuthRequests,{config,conversationId:'auth-ui-test'}))));
  </script></body></html>`);
  server = await createServer({ root: desktop, logLevel: 'error', server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const makePrompt = id => ({ request_id: id, origin: 'https://example.test', expires_at: new Date(Date.now() + 60000).toISOString(), account_identifier: null,
    fields: [{ id: 'password', label: 'Password', type: 'password', required: true }],
    options: [{ id: 'password-method', label: 'Password', field_ids: ['password'] }, { id: 'provider-method', label: 'Provider', field_ids: [] }] });
  let pending = [makePrompt('auth-ui-password')];
  const submissions = [];
  await page.exposeFunction('browserAuthInvoke', async (command, args) => {
    assert.equal(args.conversation_id, 'auth-ui-test');
    if (command === 'browser_auth_pending') return { requests: pending };
    assert.equal(command, 'browser_auth_respond');
    submissions.push(args.response); pending = [];
    await new Promise(resolve => setTimeout(resolve, 200));
    return { accepted: true };
  });
  await page.addInitScript(() => {
    window.__MEMSTACK_DESKTOP__ = { core: { invoke: (command, args) => window.browserAuthInvoke(command, args) } };
  });
  await page.goto(`${origin}/${name}`);
  await page.getByRole('combobox').selectOption('password-method');
  const field = page.getByLabel('Password', { exact: true });
  await field.fill('nonsecret-ui-fixture');
  assert.equal(await field.getAttribute('type'), 'password');
  await page.getByRole('button', { name: /Continue|继续/, exact: true }).click();
  await page.waitForFunction(() => document.querySelector('input[name=password]')?.value === '' || !document.querySelector('input[name=password]'));
  await page.waitForFunction(() => !document.querySelector('form'));
  assert.deepEqual(submissions[0], { action: 'submit', selected_option: 'password-method', values: { password: 'nonsecret-ui-fixture' } });
  assert.equal(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]).includes('nonsecret-ui-fixture')), false);
  pending = [makePrompt('auth-ui-provider')];
  await page.getByRole('combobox').selectOption('provider-method');
  assert.equal(await page.locator('input').count(), 0);
  await page.getByRole('button', { name: /Continue|继续/, exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('form'));
  assert.deepEqual(submissions[1], { action: 'submit', selected_option: 'provider-method', values: {} });
  pending = [makePrompt('auth-ui-decline')];
  await page.getByRole('combobox').selectOption('password-method');
  await page.getByLabel('Password', { exact: true }).fill('must-not-submit');
  await page.getByRole('button', { name: /Decline|拒绝/, exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('form'));
  assert.deepEqual(submissions[2], { action: 'decline', values: {} });
  pending = [{ ...makePrompt('auth-ui-qr'), fields: [], options: [], qr_image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==' }];
  await page.getByRole('img').waitFor();
  assert.equal(await page.locator('input').count(), 0);
  assert.match(await page.getByRole('img').getAttribute('src'), /^data:image\/png;base64,/);
  await page.getByRole('button', { name: /I have finished|我已完成/, exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('form'));
  assert.deepEqual(submissions[3], { action: 'submit', values: {} });
  assert.deepEqual(errors, []);
  process.stdout.write('BROWSER_AUTH_SECURE_UI_OK\n');
} finally {
  await browser?.close();
  await server?.close();
  await rm(file, { force: true });
}
