import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';

function fixture() {
  const calls = [];
  const output = [];
  const browser = { id: 'owned-cdp', type: 'cdp', family: 'cdp' };
  const cua = createFacade({
    enabledSurfaces: ['browser', 'computer'], platform: 'darwin',
    write: value => output.push(value), emitImage() {},
    rpc: async (method, params) => {
      calls.push(structuredClone({ method, ...params }));
      if (method === 'browser.operation') {
        if (params.operation === 'browsers.resolve') return browser;
        if (params.operation === 'browsers.list') return [browser];
        if (params.operation === 'tabs.list') return [{ id: 1, title: 'Owned fixture', url: 'https://fixture.test/' }];
        if (params.operation === 'ax.get') return '[2] textbox "Owned field"';
      } else {
        assert.equal(method, 'computer.call');
        if (params.tool === 'computer_resolve_app') return { app: 'owned-editor', status: 'running', process_id: 42, identity_digest: 'a'.repeat(64) };
        if (params.tool === 'computer_get_app_state') return { app: 'owned-editor', text: '[2] text field', snapshot_id: 'current', window_id: '41' };
      }
      return {};
    },
  });
  return { cua, calls, output };
}

const invalidValues = [undefined, null, false, true, 0, NaN, 1n, {}, [], new String('boxed'), Symbol('value'), () => 'value'];
const exactStrings = ['', ' \t\r\n', ' 你好😀\u0000"\\ ', '\ud800'];

for (const surface of ['tab', 'tab.ax', 'app', 'computer.set_value']) {
  test(`${surface} setValue rejects missing and non-string values before input RPC`, async () => {
    const { cua, calls } = fixture();
    const tab = surface.startsWith('tab') ? await cua.getTab(1) : undefined;
    const app = surface === 'app' ? await cua.getApp('owned-editor') : undefined;
    if (surface === 'computer.set_value') await cua.computer.get_app_state({ app: 'owned-editor' });
    const setValue = value => surface === 'tab' ? tab.setValue(2, value)
      : surface === 'tab.ax' ? tab.ax.setValue(2, value)
      : surface === 'app' ? app.setValue(2, value)
      : cua.computer.set_value({ app: 'owned-editor', element_index: 2, value });
    const before = calls.length;
    for (const value of invalidValues) {
      await assert.rejects(async () => setValue(value), { name: 'TypeError', message: /value must be a string/ });
      assert.equal(calls.length, before, 'invalid values cannot request input approval or dispatch');
    }
    if (tab || app) {
      const target = surface === 'tab.ax' ? tab.ax : tab ?? app;
      await assert.rejects(async () => target.setValue('value passed as index'), /element index/);
      assert.equal(calls.length, before, 'single-string calls cannot become implicit focused input');
    }
  });

  test(`${surface} setValue preserves every valid string exactly, including clearing`, async () => {
    const { cua, calls } = fixture();
    const tab = surface.startsWith('tab') ? await cua.getTab(1) : undefined;
    const app = surface === 'app' ? await cua.getApp('owned-editor') : undefined;
    if (surface === 'computer.set_value') await cua.computer.get_app_state({ app: 'owned-editor' });
    for (const value of exactStrings) {
      if (surface === 'tab') await tab.setValue(2, value);
      else if (surface === 'tab.ax') await tab.ax.setValue(2, value);
      else if (surface === 'app') await app.setValue(2, value);
      else await cua.computer.set_value({ app: 'owned-editor', element_index: 2, value });
      const call = calls.at(-1);
      if (tab) {
        assert.equal(call.operation, 'ax.setValue');
        assert.deepEqual(call.args, [2, value]);
      } else {
        assert.equal(call.tool, 'computer_set_value');
        assert.deepEqual(call.arguments, { app: 'owned-editor', snapshot_id: 'current', window_id: '41', element_index: 2, value });
      }
    }
  });
}

test('returned core and browser documentation state the two-argument AX signature and locator alternative', async () => {
  const { cua, output } = fixture();
  await cua.getTab(1);
  const core = output.find(value => typeof value === 'string' && value.startsWith('CUA:'));
  const browser = output.find(value => typeof value === 'string' && value.startsWith('Browser selection'));
  for (const documentation of [core, browser]) {
    assert.match(documentation, /setValue\(elementIndex, value\)/);
    assert.match(documentation, /value must be a string/);
  }
  assert.match(browser, /tab\.playwright\.getByLabel\([^)]*\)\.fill\(value\)/);
});
