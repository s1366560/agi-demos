import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createFacade } from '../src/facade.mjs';

const require = createRequire(new URL('../../../apps/desktop/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const domSource = await readFile(new URL('../../../crates/adapters-browser/assets/facade-dom.js', import.meta.url), 'utf8');

test('browser AX includes rendered save results and preserves indexed controls', async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent(`
    <title>Snapshot fixture</title>
    <main>
    <h1>Save fixture</h1>
    <p>Before <span>middle</span> after</p>
    <label>QA text<input id="text" value="initial"></label>
    <button id="save">Save</button><output id="result">Not saved</output>
    <input type="password" aria-label="Password" value="snapshot-private-value">
    <p hidden>Hidden attribute text</p>
    <p style="display:none">Display none text</p>
    <div aria-hidden="true"><span>ARIA hidden text</span><button>Hidden action</button></div>
    <p style="visibility:hidden">Invisible text</p>
    <div style="display:contents">Display contents text</div>
    <div id="shadow"><span slot="result">Slotted status</span></div>
    </main>
  `);
  await page.evaluate(() => {
    document.querySelector('#save').addEventListener('click', () => {
      document.querySelector('#result').textContent = `Saved: ${document.querySelector('#text').value}`;
    });
    document.querySelector('#shadow').attachShadow({ mode: 'open' }).innerHTML =
      'Direct shadow text<p>Shadow status</p><slot name="result"></slot><button>Shadow action</button>';
  });
  const cua = createFacade({
    write() {}, emitImage() {}, enabledSurfaces: ['browser'], platform: 'darwin',
    rpc: async (method, params) => {
      assert.equal(method, 'browser.operation');
      if (params.operation === 'browsers.list') return [{ id: 'iab', type: 'iab' }];
      if (params.operation === 'tabs.list') return { tabs: [{ id: '7', title: await page.title(), url: page.url() }] };
      if (params.operation === 'tab.claim') return {};
      return page.evaluate(`(${domSource})(${JSON.stringify({ operation: params.operation, args: params.args })})`);
    },
  });
  const tab = await cua.getTab('7', { browser: 'iab' });
  const before = await tab.getAXState();
  assert.match(before, /text "Not saved"/);
  assert.match(before, /textbox "QA text" value="initial"/);
  assert.match(before, /text "Before"\ntext "middle"\ntext "after"/);
  assert.match(before, /text "Display contents text"/);
  assert.match(before, /text "Shadow status"/);
  assert.match(before, /text "Direct shadow text"/);
  assert.match(before, /text "Slotted status"/);
  assert.equal(before.match(/button "Save"/g)?.length, 1);
  assert.doesNotMatch(before, /text "Save"|Hidden attribute|Display none|ARIA hidden|Hidden action|Invisible text|snapshot-private-value/);
  const inputIndex = Number(before.match(/\[(\d+)\] textbox "QA text"/)[1]);
  await tab.setValue(inputIndex, 'IAB_NATIVE_OK');
  await tab.playwright.getByRole('button', { name: 'Save', exact: true }).click();
  const after = await tab.getAXState();
  assert.match(after, /text "Saved: IAB_NATIVE_OK"/);
  assert.doesNotMatch(after, /Not saved/);
  assert.match(after, /textbox "QA text" value="IAB_NATIVE_OK"/);
  const shadowIndex = Number(after.match(/\[(\d+)\] button "Shadow action"/)[1]);
  assert.equal(await page.evaluate(index => globalThis.__memstackFacadeRefs[index].textContent, shadowIndex), 'Shadow action');
});
