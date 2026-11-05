import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';
import { browserAuthSelector, playwright } from '../src/locators.mjs';

test('download, file chooser and navigation handles retain event identity and cancel failed actions', async () => {
  const calls = [];
  const page = playwright(async (operation, args) => {
    calls.push({ operation, args });
    if (operation === 'playwright.waitForEvent') return { id: 'event-id', multiple: true };
    if (operation === 'playwright.armNavigation') return { id: 'navigation-id' };
    if (operation === 'download.path') return '/owned/download.txt';
    return null;
  });
  const download = await page.waitForEvent('download');
  assert.equal(await download.path({ timeoutMs: 5_000 }), '/owned/download.txt');
  assert.deepEqual(calls.at(-1).args, ['event-id', { timeoutMs: 5_000 }]);
  const chooser = await page.waitForEvent('filechooser');
  assert.equal(chooser.isMultiple(), true);
  await chooser.setFiles(['/authorized/a.txt']);
  assert.deepEqual(calls.at(-1).args, ['event-id', ['/authorized/a.txt'], {}]);
  assert.equal(await page.expectNavigation(async () => 'clicked', { waitUntil: 'domcontentloaded' }), 'clicked');
  assert.deepEqual(calls.slice(-2).map(call => call.operation), ['playwright.armNavigation', 'playwright.waitNavigation']);
  await assert.rejects(page.expectNavigation(async () => { throw new Error('click failed'); }), /click failed/);
  assert.deepEqual(calls.at(-1), { operation: 'playwright.cancelNavigation', args: ['navigation-id'] });
});

test('locator composition and authentication selectors preserve private locator chains', async () => {
  const calls = [];
  const page = playwright(async (operation, args) => {
    calls.push({ operation, args });
    return args[1] === 'count' ? 2 : null;
  });
  const candidate = page.getByRole('textbox').filter({ has: page.getByText('Account'), hasNot: page.getByTestId('disabled') });
  const exact = candidate.and(page.getByLabel('Email')).or(page.locator('#email'));
  const all = await exact.all();
  assert.equal(all.length, 2);
  await all[1].fill('name@example.test');
  assert.equal(calls.at(-1).args[0].at(-1).kind, 'nth');
  assert.deepEqual(calls.at(-1).args[0].at(-1).args, [1]);
  const selector = browserAuthSelector(exact);
  assert.equal(selector.steps[0].kind, 'getByRole');
  assert.equal(selector.steps[1].args[0].has[0].kind, 'getByText');
  assert.deepEqual(browserAuthSelector('#email'), { steps: [{ kind: 'locator', args: ['#email'] }] });
  assert.throws(() => exact.and({ selector: '#email' }), /another locator/);
  assert.throws(() => browserAuthSelector({ steps: [] }), /CSS string or locator/);
});

test('raw browser input maps duration and selection enums to host contracts and rejects unsupported observations', async () => {
  const calls = [];
  const cua = createFacade({ enabledSurfaces: ['browser'], platform: 'darwin', write() {}, emitImage() {}, rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return [{ id: 'iab', type: 'iab' }];
    if (params.operation === 'tabs.list') return [{ id: 'tab' }];
    if (params.operation === 'ax.get') return { text: 'Ready' };
    return null;
  } });
  const tab = await cua.getTab('tab', { browser: 'iab' });
  await tab.ax.pressKey(null, 'Return', { duration: 0.25 });
  assert.deepEqual(calls.at(-1).args, [null, 'Return', { duration_ms: 250 }]);
  await tab.ax.click([1, 2], { duration: 0.25 });
  assert.equal(calls.at(-1).args[0].duration_ms, 250);
  await tab.drag([1, 2], [3, 4]);
  assert.deepEqual(calls.at(-1).args, [{ x: 1, y: 2 }, { x: 3, y: 4 }]);
  await tab.selectText(0, 'Account', { selectionType: 'cursor_before' });
  assert.equal(calls.at(-1).args[2].selectionType, 'before');
  const before = calls.length;
  await assert.rejects(tab.ax.get('unsupported'), /observation mode/);
  await assert.rejects(tab.ax.write('unsupported'), /observation mode/);
  assert.equal(calls.length, before);
});

test('browser credential requests serialize locator selectors without accepting forged selector objects', async () => {
  const calls = [];
  const cua = createFacade({ enabledSurfaces: ['browser'], platform: 'darwin', write() {}, emitImage() {}, rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return [{ id: 'iab', type: 'iab' }];
    if (params.operation === 'tabs.list') return [{ id: 'tab' }];
    if (params.operation === 'ax.get') return { text: 'Ready' };
    if (params.operation === 'capabilities.list') return ['browserAuth'];
    return { status: 'completed' };
  } });
  const tab = await cua.getTab('tab', { browser: 'iab' });
  const auth = await tab.capabilities.get('browserAuth');
  await auth.request({ origin: 'https://example.test', fields: [{ id: 'password', label: 'Password', type: 'password', selector: tab.playwright.getByLabel('Password') }],
    options: [{ id: 'login', label: 'Login', selector: '#login' }], submit: { selector: '#submit', action: 'click' } });
  assert.equal(calls.at(-1).args[0].fields[0].selector.steps[0].kind, 'getByLabel');
  assert.equal(calls.at(-1).args[0].submit.selector.steps[0].kind, 'locator');
  const before = calls.length;
  assert.throws(() => auth.request({ fields: [{ selector: { steps: [] } }] }), /CSS string or locator/);
  assert.equal(calls.length, before);
});
