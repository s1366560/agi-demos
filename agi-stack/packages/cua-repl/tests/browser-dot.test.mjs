import assert from 'node:assert/strict';
import test from 'node:test';
import { createFacade } from '../src/facade.mjs';

test('Dot user inventory and claimed inventory differ, and binding claims before reading', async () => {
  const calls = []; let claimed = false;
  const info = { id: 'dot:live', family: 'dot', type: 'iab', userTabs: true };
  const row = { id: '7', title: 'Main tab', url: 'https://example.test' };
  const cua = createFacade({ write() {}, emitImage() {}, enabledSurfaces: ['browser'], rpc: async (_, params) => {
    calls.push(params.operation);
    if (params.operation === 'browsers.list') return [info];
    if (params.operation === 'user.openTabs') return { tabs: [row] };
    if (params.operation === 'tabs.list') return { tabs: claimed ? [row] : [] };
    if (params.operation === 'tab.claim') { claimed = true; return {}; }
    if (params.operation === 'ax.get') { assert.equal(claimed, true); return { text: 'Main tab' }; }
    throw new Error(params.operation);
  }});
  const browser = await cua.getBrowser({ id: info.id });
  assert.deepEqual(await browser.tabs.list(), []);
  assert.equal((await browser.user.openTabs()).length, 1);
  assert.equal((await cua.listTabs({ browser: info.id, emit: false })).length, 1);
  assert.equal(claimed, false);
  const tab = await browser.user.claimTab(row);
  assert.equal(tab.id, '7');
  assert.equal((await browser.tabs.list()).length, 1);
  assert.ok(calls.indexOf('tab.claim') < calls.indexOf('ax.get'));
});
