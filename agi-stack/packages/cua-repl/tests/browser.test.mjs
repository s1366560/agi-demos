import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createFacade } from '../src/facade.mjs';

const require = createRequire(new URL('../../../apps/desktop/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const domSource = await readFile(new URL('../../../crates/adapters-browser/assets/facade-dom.js', import.meta.url), 'utf8');

test('facade drives real Chromium DOM including iframe, shadow DOM and live controls', async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent('<title>Facade fixture</title><label>Full name<input id="name"></label><button id="save">Save</button><input type="checkbox" aria-label="Agree"><select aria-label="Color"><option value="red">Red</option><option value="blue">Blue</option></select><div id="shadow"></div><iframe srcdoc="<button>Inside frame</button>"></iframe>');
  await page.evaluate(() => {
    document.querySelector('#save').addEventListener('click', () => { document.body.dataset.saved = document.querySelector('#name').value; });
    document.querySelector('#shadow').attachShadow({ mode: 'open' }).innerHTML = '<button>Shadow button</button>';
  });
  const trace = [];
  const cua = createFacade({ write() {}, emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin', rpc: async (method, params) => {
    assert.equal(method, 'browser.operation'); trace.push(params);
    if (params.operation === 'browsers.list') return [{ id: 'iab', type: 'iab' }];
    if (params.operation === 'tabs.list') return { tabs: [{ id: '7', title: await page.title(), url: page.url() }] };
    if (params.operation === 'tab.claim') return {};
    return page.evaluate(`(${domSource})(${JSON.stringify({ operation: params.operation, args: params.args })})`);
  } });
  const selected = await cua.getBrowser({ id: 'iab' });
  assert.equal(selected.history, undefined);
  assert.equal(selected.tabs.content, undefined);
  assert.equal(selected.user, undefined);
  assert.equal(trace.some(call => call.operation === 'tabs.new'), false);
  const tab = await selected.tabs.get('7');
  await tab.playwright.getByLabel('Full name').fill('Ada');
  await tab.playwright.getByRole('button', { name: 'Save', exact: true }).click();
  assert.equal(await page.getAttribute('body', 'data-saved'), 'Ada');
  await tab.playwright.getByRole('checkbox', { name: 'Agree' }).check();
  assert.equal(await page.locator('input[type=checkbox]').isChecked(), true);
  assert.deepEqual(await tab.playwright.getByLabel('Color').selectOption('blue'), ['blue']);
  assert.equal(await tab.playwright.getByRole('button', { name: 'Shadow button' }).count(), 1);
  assert.equal(await tab.playwright.frameLocator('iframe').getByRole('button', { name: 'Inside frame' }).count(), 1);
  assert.equal(await tab.playwright.getByRole('button').filter({ hasText: 'Save' }).innerText(), 'Save');
  await assert.rejects(cua.getTab({ url: page.url() }), /explicit browser/);
  await assert.rejects(cua.getTab({ mention: 'plugin://browser?mention=tab-v1&browserId=iab&tabId=7&title=Old&url=about%3Ablank' }), /unavailable or has changed/);
  assert.equal(trace.some(call => call.operation === 'tabs.new'), false);
});

test('MCP Apps refuses native input before RPC and keeps DOM operations available', async () => {
  const calls = [];
  const cua = createFacade({ write() {}, emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin', rpc: async (_method, params) => {
    calls.push(params.operation);
    if (params.operation === 'browsers.list') return [{ id: 'mcpapps', type: 'mcpapps' }];
    if (params.operation === 'tabs.list') return { tabs: [{ id: 'opaque', title: 'Fixture', url: 'mcpapp://fixture' }] };
    if (params.operation === 'playwright.domSnapshot') return '[0] button Example';
    return {};
  } });
  const tab = await cua.getTab('opaque', { browser: 'mcpapps' });
  const before = calls.length;
  assert.throws(() => tab.click(0), /DOM-only/);
  assert.throws(() => tab.cua.type({ text: 'text' }), /DOM-only/);
  assert.equal(calls.length, before);
  await tab.playwright.getByRole('button').click();
  assert.equal(calls.at(-1), 'playwright.locator');
});

test('provider history preserves Date inputs and capability documentation uses advertised methods', async () => {
  const calls = [];
  const output = [];
  const cua = createFacade({ write: value => output.push(value), emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin', rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return [{ id: 'chrome', type: 'chrome' }];
    if (params.operation === 'capabilities.list') return ['management'];
    if (params.operation === 'history') return [];
    return {};
  } });
  const browser = await cua.getBrowser({ id: 'chrome' });
  const from = new Date('2026-10-20T00:00:00Z');
  await browser.history({ from, limit: 5 });
  assert.deepEqual(calls.at(-1).args, [{ from: from.toISOString(), limit: 5 }]);
  const management = await browser.capabilities.get('management');
  assert.match(await management.documentation(), /getAuditTrail/);
  assert.match(output.at(-1), /Shared groups/);
  await assert.rejects(browser.capabilities.get('visibility'), /unavailable/);
  assert.equal(browser.user.getTabContext, undefined);
});

test('browser instances with matching tab ids remain independently selectable and old handles cannot rebind', async () => {
  const firstId = `chrome:${'1'.repeat(32)}:${'a'.repeat(32)}`;
  const secondId = `chrome:${'2'.repeat(32)}:${'b'.repeat(32)}`;
  const replacementId = `chrome:${'1'.repeat(32)}:${'c'.repeat(32)}`;
  const first = { id: firstId, type: 'chrome', metadata: { profileId: 'profile-one', extensionInstanceId: 'worker-one', connectionGeneration: 'generation-one' } };
  const second = { id: secondId, type: 'chrome', metadata: { profileId: 'profile-two', extensionInstanceId: 'worker-two', connectionGeneration: 'generation-two' } };
  let available = [first, second];
  const calls = [];
  const cua = createFacade({ write() {}, emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin', rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return structuredClone(available);
    if (!available.some(browser => browser.id === params.browserId)) throw new Error('browser instance expired');
    if (params.operation === 'tabs.list') return { tabs: [{ id: '7', title: 'Same title', url: 'https://example.test/same' }] };
    if (params.operation === 'ax.get') return { text: '[0] button Save' };
    if (params.operation === 'history') return [{ url: 'https://example.test/visit', dateVisited: '2026-10-22T00:00:00Z' }];
    return {};
  } });
  await assert.rejects(cua.getBrowser({ id: 'chrome' }), /ambiguous/);
  await assert.rejects(cua.getBrowser({ url: 'https://example.test/same' }), /ambiguous/);
  const browserOne = await cua.getBrowser({ extensionInstanceId: 'worker-one' });
  const browserTwo = await cua.getBrowser({ id: secondId });
  assert.equal(browserOne.browserId, firstId);
  assert.equal(browserTwo.browserId, secondId);
  assert.equal(typeof browserOne.history, 'function');
  assert.equal(typeof browserOne.user.claimTab, 'function');
  const tabs = await cua.listTabs({ emit: false });
  assert.deepEqual(tabs.map(tab => [tab.id, tab.browserId]), [['7', firstId], ['7', secondId]]);
  const tabOne = await browserOne.tabs.get('7');
  const tabTwo = await browserTwo.tabs.get('7');
  await tabOne.playwright.getByRole('button', { name: 'Save' }).click();
  assert.equal(calls.at(-1).browserId, firstId);
  await tabTwo.playwright.getByRole('button', { name: 'Save' }).click();
  assert.equal(calls.at(-1).browserId, secondId);
  available = [{ ...first, id: replacementId, metadata: { ...first.metadata, connectionGeneration: 'generation-three' } }, second];
  await assert.rejects(tabOne.playwright.getByRole('button').click(), /instance expired/);
  assert.equal(calls.at(-1).browserId, firstId);
  await assert.rejects(browserOne.history({ limit: 1 }), /instance expired/);
  assert.equal(calls.at(-1).browserId, firstId);
  await assert.rejects(browserOne.tabs.get('7'), /unavailable/);
  const replacement = await cua.getBrowser({ extensionInstanceId: 'worker-one' });
  assert.equal(replacement.browserId, replacementId);
  await tabTwo.playwright.getByRole('button').click();
  assert.equal(calls.at(-1).browserId, secondId);
});

test('opaque IAB and Edge identities preserve their provider-specific facade methods', async () => {
  const browsers = [
    { id: `iab:${'3'.repeat(32)}:${'d'.repeat(32)}`, type: 'iab' },
    { id: `edge:${'4'.repeat(32)}:${'e'.repeat(32)}`, type: 'edge' },
  ];
  const calls = [];
  const cua = createFacade({ write() {}, emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin', rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return browsers;
    if (params.operation === 'tabs.new') return { id: '7' };
    if (params.operation === 'ax.get') return { text: 'Fixture' };
    return {};
  } });
  const iab = await cua.getBrowser({ id: 'iab' });
  const edge = await cua.getBrowser({ id: 'edge' });
  assert.equal(iab.history, undefined);
  assert.equal(iab.user, undefined);
  assert.equal(typeof edge.history, 'function');
  assert.equal(typeof edge.user.openTabs, 'function');
  await edge.history({ limit: 1 });
  assert.equal(calls.at(-1).browserId, browsers[1].id);
  await cua.createBrowserTab('iab', 'https://example.test/', { visible: true });
  assert.equal(calls.find(call => call.operation === 'tabs.new').browserId, browsers[0].id);
});
