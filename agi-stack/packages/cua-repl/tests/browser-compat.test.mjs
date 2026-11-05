import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';

function fixture() {
  const calls = [];
  const browsers = [{ id: 'chrome-profile', family: 'chrome', type: 'extension', metadata: { extensionInstanceId: 'profile-one' } }, { id: 'iab', type: 'iab' }];
  const cua = createFacade({ enabledSurfaces: ['browser'], platform: 'darwin', write() {}, emitImage() {}, rpc: async (_method, params) => {
    calls.push(params);
    if (params.operation === 'browsers.list') return browsers;
    if (params.operation === 'browsers.resolve') return browsers[0];
    if (params.operation === 'capabilities.list') return ['visibility'];
    if (params.operation === 'tabs.new') return { id: 'new' };
    if (params.operation === 'tabs.list') return [{ id: 'owned', providerTabId: 'provider', title: 'Page title', url: 'https://example.test/' }];
    if (params.operation === 'ax.get') return 'Page state';
    return {};
  } });
  return { cua, calls };
}

test('host resolves default and URL browsers while explicit identities retain extension methods', async () => {
  const { cua, calls } = fixture();
  assert.equal((await cua.getBrowser()).browserId, 'chrome-profile');
  assert.deepEqual(calls.find(call => call.operation === 'browsers.resolve').args, [{}]);
  assert.equal((await cua.getBrowser({ url: 'example.test/path' })).browserId, 'chrome-profile');
  assert.deepEqual(calls.filter(call => call.operation === 'browsers.resolve').at(-1).args, [{ url: 'https://example.test/path' }]);
  const browser = await cua.getBrowser({ extensionInstanceId: 'profile-one' });
  assert.equal(typeof browser.history, 'function');
  assert.equal(typeof browser.user.claimTab, 'function');
  await assert.rejects(cua.getBrowser({ id: 'chrome-profile', extensionInstanceId: 'profile-one' }), /either|both/);
  assert.equal((await cua.getTab('owned')).id, 'owned');
  assert.equal(calls.filter(call => call.operation === 'tabs.list').at(-1).browserId, 'chrome-profile');
});

test('browser documentation gives usable string identity examples', async () => {
  const emitted = [];
  const cua = createFacade({ enabledSurfaces: ['browser'], platform: 'darwin', write: value => emitted.push(value), emitImage() {}, rpc: async (_method, params) => {
    if (params.operation === 'browsers.resolve') return { id: 'cdp:provider:generation', family: 'cdp', type: 'cdp' };
    if (params.operation === 'browsers.list') return [{ id: 'cdp:provider:generation', family: 'cdp', type: 'cdp' }];
    if (params.operation === 'tabs.list') return [{ id: '1', url: 'http://127.0.0.1/' }];
    if (params.operation === 'tabs.new') return { id: '2', url: 'http://127.0.0.1/' };
    return {};
  } });
  const browser = await cua.getBrowser();
  assert.ok(emitted.some(value => String(value).includes('browser: browser.browserId')));
  assert.ok(emitted.some(value => String(value).includes('createBrowserTab(browser.browserId')));
  assert.equal((await cua.getTab('1', { browser: browser.browserId })).id, '1');
  await assert.rejects(cua.getTab('1', { browser }), /browser ID string.*browser\.browserId/);
  assert.equal((await cua.createBrowserTab(browser.browserId, 'http://127.0.0.1/')).id, '2');
});

test('tab creation validates support, applies settings and opens a normalized URL in order', async () => {
  const { cua, calls } = fixture();
  await cua.createBrowserTab('iab', 'example.test', { sessionName: 'Research', visible: false });
  const mutations = calls.filter(call => ['nameSession', 'capability.visibility.set', 'tabs.new'].includes(call.operation));
  assert.deepEqual(mutations.map(call => [call.operation, call.args]), [
    ['nameSession', ['Research']], ['capability.visibility.set', [false]], ['tabs.new', ['https://example.test']],
  ]);
  const before = calls.length;
  await assert.rejects(cua.createBrowserTab('iab', 'example.test', { invisible: true }), /unknown/);
  assert.equal(calls.length, before);
});

test('explicit stable provider references resolve a new generation without rebinding expired live identities', async () => {
  const browsers = [{ id: 'cdp:first-generation', family: 'cdp', type: 'cdp', metadata: { stableId: 'cdp:configured-provider' } }];
  const cua = createFacade({ enabledSurfaces: ['browser'], platform: 'darwin', write() {}, emitImage() {},
    rpc: async (_method, params) => params.operation === 'browsers.list' ? browsers : [] });
  assert.equal((await cua.getBrowser({ id: 'cdp:configured-provider' })).browserId, 'cdp:first-generation');
  browsers[0] = { ...browsers[0], id: 'cdp:second-generation' };
  await assert.rejects(cua.getBrowser({ id: 'cdp:first-generation' }), /unavailable/);
  assert.equal((await cua.getBrowser({ id: 'cdp:configured-provider' })).browserId, 'cdp:second-generation');
  browsers.push({ ...browsers[0], id: 'cdp:duplicate-generation' });
  await assert.rejects(cua.getBrowser({ id: 'cdp:configured-provider' }), /ambiguous/);
});

test('mentions bind exact provider identity and reject duplicates, mismatched browsers and stale metadata before claim', async () => {
  const { cua, calls } = fixture();
  const mention = 'plugin://chrome@openai-bundled?mention=tab-v1&browserId=profile-one&tabId=provider&title=Page%20title&url=https%3A%2F%2Fexample.test%2F';
  assert.equal((await cua.getTab({ mention })).id, 'owned');
  const claims = () => calls.filter(call => call.operation === 'tab.claim').length;
  const before = claims();
  await assert.rejects(cua.getTab({ mention: `${mention}&tabId=provider` }), /duplicate|mention/);
  await assert.rejects(cua.getTab({ mention }, { browser: 'iab' }), /match|browser/);
  await assert.rejects(cua.getTab({ mention: mention.replace('Page%20title', 'Stale') }), /unavailable|changed|stale/i);
  await assert.rejects(cua.getTab({ mention: mention.replace('chrome@openai-bundled', 'unknown@openai-bundled') }), /mention/);
  assert.equal(claims(), before);
});
