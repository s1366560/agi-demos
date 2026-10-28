import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';

test('combined state keeps available surfaces, reports failed ones and emits one coherent observation', async () => {
  const output = [];
  const calls = [];
  let failed = 'computer';
  const cua = createFacade({
    platform: 'darwin', write: value => output.push(value), emitImage() {},
    rpc: async (method, params) => {
      calls.push({ method, params });
      if (method === 'computer.call') {
        if (failed === 'computer') return { error: { code: 'permission_required', message: 'Accessibility unavailable' } };
        return { apps: [{ id: 'fixture.app', display_name: 'Fixture', is_running: true }] };
      }
      if (failed === 'browser') throw new Error('Browser bridge offline');
      if (params.operation === 'browsers.list') return [{ id: 'chrome:profile:generation', type: 'chrome' }];
      if (params.operation === 'tabs.list') return { tabs: [{ tabId: 7, title: 'Fixture tab', url: 'https://fixture.invalid/' }] };
      throw new Error('unexpected state operation');
    },
  });

  const partial = await cua.getState();
  assert.deepEqual(partial.apps, []);
  assert.deepEqual(partial.errors, ['computer: Accessibility unavailable']);
  assert.deepEqual(partial.browsers[0].tabs, [{
    tabId: 7, id: '7', browserId: 'chrome:profile:generation',
    title: 'Fixture tab', url: 'https://fixture.invalid/',
  }]);
  assert.equal(output.length, 2);
  assert.equal(typeof output[0], 'string');
  assert.equal(output[1], partial);
  assert.ok(calls.every(({ method, params }) => method === 'computer.call'
    ? params.tool === 'computer_list_apps'
    : ['browsers.list', 'tabs.list'].includes(params.operation)));

  failed = 'browser';
  const quiet = await cua.getState({ emit: false });
  assert.equal(output.length, 2);
  assert.equal(quiet.apps[0].displayName, 'Fixture');
  assert.equal(quiet.apps[0].isRunning, true);
  assert.deepEqual(quiet.browsers, []);
  assert.deepEqual(quiet.errors, ['browser: Browser bridge offline']);

  failed = undefined;
  const restored = await cua.getState({ emit: false });
  assert.equal(Object.hasOwn(restored, 'errors'), false);
  assert.equal(restored.apps.length, 1);
  assert.equal(restored.browsers.length, 1);
});

test('surface restrictions prevent native discovery and documentation can be replayed without invoking tools', async () => {
  const output = [];
  const calls = [];
  const cua = createFacade({
    enabledSurfaces: ['browser'], platform: 'darwin',
    write: value => output.push(value), emitImage() {},
    rpc: async (method, params) => {
      calls.push({ method, params });
      assert.equal(method, 'browser.operation');
      if (params.operation === 'browsers.list') return [{ id: 'iab', type: 'iab' }];
      if (params.operation === 'tabs.list') return [];
      throw new Error('unexpected discovery operation');
    },
  });
  assert.equal(cua.computer, undefined);
  assert.equal(cua.getApp, undefined);
  await cua.rewriteDocumentation();
  const core = output[0];
  await cua.initialize();
  assert.deepEqual(output, [core]);
  await cua.getBrowser({ id: 'iab' });
  const browser = output[1];
  assert.equal(typeof browser, 'string');
  assert.notEqual(browser, core);
  await cua.getBrowser({ id: 'iab' });
  assert.deepEqual(output, [core, browser]);
  const beforeReplay = calls.length;
  await cua.rewriteDocumentation();
  assert.equal(calls.length, beforeReplay);
  assert.deepEqual(output, [core, browser, core, browser]);
  assert.deepEqual(await cua.getState({ emit: false }), {
    apps: [], browsers: [{ id: 'iab', type: 'iab', tabs: [] }],
  });
  for (const enabledSurfaces of [[], ['unknown'], ['browser', 'unknown'], 'browser']) {
    assert.throws(() => createFacade({ enabledSurfaces }), /enabledSurfaces/);
  }
});
