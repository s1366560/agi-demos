import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const require = createRequire(new URL('../../../apps/desktop/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const domSource = await readFile(new URL('../../../crates/adapters-browser/assets/facade-dom.js', import.meta.url), 'utf8');
const textValues = ['{"count":1}', '[1,true,null]', '1', '0', 'true', 'false', 'null', '"quoted"', '', '{"error":"application data"}'];
const dataValues = [1, 0, true, false, null, [1, 'true', null], { count: 1 }, { error: 'application data', count: 1 }, { error: { code: 'business', message: 'visible data' } }];

function kernel(t, host) {
  const child = spawn(process.execPath, ['--experimental-vm-modules', fileURLToPath(new URL('../src/cli.mjs', import.meta.url))], { stdio: ['pipe', 'pipe', 'pipe'] });
  const replies = new Map();
  let ready;
  const started = new Promise(resolve => { ready = resolve; });
  createInterface({ input: child.stdout }).on('line', async line => {
    const frame = JSON.parse(line);
    if (frame.type === 'ready') ready();
    else if (frame.type === 'result') replies.get(frame.id)?.(frame);
    else if (frame.type === 'rpc') {
      let response;
      try { response = { result: await host(frame.method, frame.params) }; }
      catch (error) { response = { error: { code: error.code ?? 'fixture_host_error', message: error.message } }; }
      child.stdin.write(`${JSON.stringify({ type: 'rpc_response', id: frame.id, ...response })}\n`);
    }
  });
  t.after(() => child.kill());
  let sequence = 0;
  return async code => {
    await started;
    const id = `value-${++sequence}`;
    const response = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('browser value RPC timed out')), 10_000);
      replies.set(id, frame => { clearTimeout(timeout); replies.delete(id); resolve(frame); });
    });
    child.stdin.write(`${JSON.stringify({ type: 'execute', id, code, context: { enabledSurfaces: ['browser'] } })}\n`);
    return response;
  };
}

test('real Node JSONL and DOM facade preserve browser result types across providers', async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent('<title>Browser value fixture</title><button id="enabled">Enabled</button><button id="disabled" disabled>Disabled</button><div id="hidden" hidden>Hidden</div>');
  await page.evaluate(values => {
    values.forEach((value, index) => {
      const node = document.createElement('div');
      node.id = `text-${index}`;
      node.className = 'value';
      node.textContent = value;
      node.setAttribute('data-value', value);
      document.body.append(node);
    });
  }, textValues);
  for (const family of ['chrome', 'edge', 'iab', 'mcpapps']) {
    await t.test(family, async t => {
      const operations = [];
      const execute = kernel(t, async (method, params) => {
        assert.equal(method, 'browser.operation');
        operations.push(params.operation);
        if (params.operation === 'browsers.list') return [{ id: family, type: family }];
        assert.equal(params.browserId, family);
        if (params.operation === 'tabs.list') return { tabs: [{ id: '7', title: await page.title(), url: page.url() }] };
        assert.equal(params.tabId, '7');
        if (params.operation === 'tab.claim') return {};
        if (params.operation === 'playwright.locator' && params.args[0][0]?.args[0] === '#transport-error') {
          throw Object.assign(new Error('fixture authorization rejected'), { code: 'fixture_permission_denied' });
        }
        return page.evaluate(`(${domSource})(${JSON.stringify({ operation: params.operation, args: params.args })})`);
      });
      assert.equal((await execute(`var tab = await cua.getTab('7', {browser:${JSON.stringify(family)}});`)).ok, true);
      const observed = await execute(`
        var parsed = JSON.parse(await tab.playwright.locator('#text-0').innerText());
        var strings = [];
        for (var index = 0; index < ${textValues.length}; index++) {
          var item = tab.playwright.locator('#text-' + index);
          strings.push([await item.innerText(), await item.textContent(), await item.getAttribute('data-value')]);
        }
        var typed = [];
        for (var value of ${JSON.stringify(dataValues)}) {
          try { typed.push({value: await tab.playwright.evaluate(value => value, value)}); }
          catch (error) { typed.push({thrown: error.message}); }
        }
        var adjacent = [await tab.playwright.locator('.value').count(), await tab.playwright.locator('#enabled').isEnabled(), await tab.playwright.locator('#disabled').isEnabled(), await tab.playwright.locator('#enabled').isVisible(), await tab.playwright.locator('#hidden').isVisible(), await tab.playwright.locator('#enabled').getAttribute('missing'), await tab.playwright.locator('.value').allTextContents()];
        ({strings, typed, adjacent, parsed});
      `);
      assert.equal(observed.ok, true, JSON.stringify(observed));
      assert.deepEqual(observed.value.strings, textValues.map(value => [value, value, value]));
      assert.deepEqual(observed.value.typed, dataValues.map(value => ({ value })));
      assert.deepEqual(observed.value.adjacent, [textValues.length, true, false, true, false, null, textValues]);
      assert.deepEqual(observed.value.parsed, { count: 1 });

      const applicationData = await execute(`await tab.playwright.locator('#text-0').evaluate(node => ({error:'page data', text:node.textContent}));`);
      assert.equal(applicationData.ok, true, JSON.stringify(applicationData));
      assert.deepEqual(applicationData.value, { error: 'page data', text: textValues[0] });
      const transportError = await execute(`await tab.playwright.locator('#transport-error').innerText();`);
      assert.equal(transportError.ok, false);
      assert.equal(transportError.error.code, 'fixture_permission_denied');
      assert.equal(transportError.error.message, 'fixture authorization rejected');
      assert.equal(operations.filter(operation => operation === 'tab.claim').length, 1);
    });
  }
});
