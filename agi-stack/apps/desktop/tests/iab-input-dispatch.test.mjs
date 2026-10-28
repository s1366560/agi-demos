import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const desktopRoot = process.env.AGISTACK_IAB_DESKTOP_ROOT ?? fileURLToPath(new URL('..', import.meta.url));
const require = createRequire(join(desktopRoot, 'package.json'));
const ts = require('typescript');
const moduleRoot = join(desktopRoot, 'electron/main/iab');

function fixture(sendCommand, executeScript = async () => { throw Error('input must not synthesize page events'); }) {
  const calls = [];
  const views = [];
  const windows = [];
  class View {
    constructor() {
      let destroyed = false;
      const contents = {
        isDestroyed: () => destroyed,
        loadURL: async () => {},
        on: () => {},
        setWindowOpenHandler: () => {},
        executeJavaScript: executeScript,
        close: () => { destroyed = true; },
        debugger: {
          isAttached: () => false,
          attach: () => {},
          detach: () => {},
          on: () => {},
          sendCommand: async (method, params, sessionId) => {
            calls.push({ method, params, sessionId, target: views.indexOf(this) });
            return sendCommand(method, params, sessionId);
          },
        },
      };
      this.webContents = contents;
      views.push(this);
    }
    setBounds(bounds) { this.bounds = bounds; }
    setVisible(visible) { this.visible = visible; }
  }
  const cache = new Map();
  function load(name) {
    if (!name.startsWith('./')) return require(name);
    const path = join(moduleRoot, `${name.slice(2)}.ts`);
    if (cache.has(path)) return cache.get(path).exports;
    const sourcePath = name === './viewPool' ? process.env.AGISTACK_IAB_VIEW_POOL_SOURCE ?? path : path;
    const source = readFileSync(sourcePath, 'utf8');
    const module = { exports: {} };
    cache.set(path, module);
    const compiled = ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    });
    new Function('require', 'exports', 'module', '__dirname', compiled.outputText)(
      dependency => dependency === 'electron'
        ? { WebContentsView: View, BrowserWindow: function (options) {
          assert.equal(options.show, false);
          assert.equal(options.focusable, false);
          const window = hostFixture();
          windows.push(window);
          return window;
        }, session: { fromPartition: () => ({}) } }
        : load(dependency),
      module.exports, module, dirname(path),
    );
    return module.exports;
  }
  const { IabViewPool } = load('./viewPool');
  const pool = new IabViewPool({ preloadPath: '/unused-test-preload', cursorScriptPath: () => '/unused-test-cursor' });
  return { pool, calls, views, windows };
}

test('IAB input preserves the exact authorized command and target session through Chromium', async () => {
  const { pool, calls } = fixture(async () => ({}));
  const tab = await pool.createTab();
  for (const [method, params] of [
    ['Input.dispatchMouseEvent', { type: 'mousePressed', x: 12.5, y: 40, button: 'left', clickCount: 1, modifiers: 9 }],
    ['Input.dispatchMouseEvent', { type: 'mouseReleased', x: 12.5, y: 40, button: 'left', clickCount: 1 }],
    ['Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }],
    ['Input.insertText', { text: 'QA text' }],
  ]) {
    assert.deepEqual(await pool.executeCdp(tab, method, params, undefined), {});
    assert.deepEqual(calls.at(-1), { method, params, sessionId: undefined, target: 0 });
  }
  const params = { type: 'mouseMoved', x: 20, y: 30 };
  await pool.executeCdp(tab, 'Input.dispatchMouseEvent', params, 'owned-child-session');
  assert.deepEqual(calls.at(-1), { method: 'Input.dispatchMouseEvent', params, sessionId: 'owned-child-session', target: 0 });
  pool.destroyAll();
});

test('Chromium rejection and unavailable tabs cannot be reported as successful input', async () => {
  const { pool, calls } = fixture(async () => { throw Error('Invalid mouse event type'); });
  const tab = await pool.createTab();
  await assert.rejects(pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type: 'mouseDragged' }), /Invalid mouse event type/);
  pool.closeTab(tab);
  await assert.rejects(pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type: 'mousePressed', x: 1, y: 2 }), /does not exist/);
  await assert.rejects(pool.executeCdp(999, 'Input.insertText', { text: 'foreign' }), /does not exist/);
  assert.equal(calls.length, 1);
});

test('actual Chromium IAB input saves with trusted events, default actions and correct coordinates', { skip: process.env.AGISTACK_IAB_INPUT_CHROMIUM_TESTS !== '1', timeout: 20_000 }, async () => {
  const { chromium } = require('@playwright/test');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
    const other = await browser.newPage();
    await other.setContent('<button onclick="document.body.dataset.clicked=1">Other tab</button>');
    await page.setContent(`<!doctype html><style>body{margin:0} main{padding:80px 120px} #scroll{height:70px;overflow:auto} #scroll div{height:600px}</style>
      <main><form><label>QA text <input id="text"></label><button id="save">Save QA text</button></form>
      <output id="result">Not saved</output><label><input type="checkbox" id="check">QA check</label>
      <div id="scroll"><div>Scroll content</div></div></main>
      <script>window.events=[]; for(const type of ['pointerdown','mousedown','pointerup','mouseup','click','keydown','keyup','input']) document.addEventListener(type,event=>events.push({type:event.type,trusted:event.isTrusted,target:event.target.id})); document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();result.textContent=JSON.stringify({value:text.value,trusted:event.isTrusted});});</script>`);
    const cdp = await page.context().newCDPSession(page);
    const { pool } = fixture((method, params) => cdp.send(method, params), script => page.evaluate(script));
    const tab = await pool.createTab();
    async function click(selector) {
      const point = await page.locator(selector).evaluate(element => { const rect = element.getBoundingClientRect(); return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }; });
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
        await pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type, ...point, button: 'left', clickCount: 1 });
      }
    }
    await click('#text');
    await pool.executeCdp(tab, 'Input.insertText', { text: 'IAB_NATIVE_OK' });
    await click('#save');
    assert.equal(await page.locator('#result').textContent(), JSON.stringify({ value: 'IAB_NATIVE_OK', trusted: true }));
    const clicks = await page.evaluate(() => events.filter(event => event.type === 'click'));
    assert.ok(clicks.some(event => event.target === 'save' && event.trusted === true));
    assert.ok((await page.evaluate(() => events)).every(event => event.trusted === true));
    await click('#check');
    assert.equal(await page.locator('#check').isChecked(), true);
    const scroll = await page.locator('#scroll').boundingBox();
    await pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type: 'mouseWheel', x: scroll.x + 10, y: scroll.y + 10, deltaX: 0, deltaY: 120 });
    await page.waitForFunction(() => document.querySelector('#scroll').scrollTop > 0);
    await click('#text');
    await pool.executeCdp(tab, 'Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await pool.executeCdp(tab, 'Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    assert.ok((await page.evaluate(() => events)).some(event => event.type === 'keydown' && event.trusted));
    await assert.rejects(pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type: 'mouseDragged', x: 1, y: 2 }), /Unexpected event type/);
    assert.equal(await other.evaluate(() => document.body.dataset.clicked ?? null), null);
    pool.destroyAll();
  } finally {
    await browser.close();
  }
});

function hostFixture() {
  const children = new Set();
  let destroyed = false;
  return {
    children,
    isDestroyed: () => destroyed,
    destroy: () => { destroyed = true; },
    show: () => { throw Error('hidden tab must not show its host'); },
    contentView: {
      addChildView: view => children.add(view),
      removeChildView: view => children.delete(view),
    },
  };
}

test('hidden IAB tabs retain rendering bounds without joining the native view tree', async () => {
  const { pool, views, windows } = fixture(async () => ({}));
  const host = hostFixture();
  pool.setHostWindow(host);
  const first = await pool.createTab();
  await pool.createTab();
  assert.equal(windows.length, 2);
  assert.ok(windows.every(window => window.isDestroyed() && window.children.size === 0));
  for (const view of views) {
    assert.ok(view.bounds.width > 0 && view.bounds.height > 0);
    assert.equal(view.visible, false);
  }
  assert.equal(host.children.size, 0);
  const bounds = { x: 20, y: 40, width: 850, height: 620 };
  pool.focusTab(first);
  pool.showPane(bounds);
  assert.deepEqual([...host.children], [views[0]]);
  assert.equal(views[0].visible, true);
  pool.hidePane();
  assert.equal(host.children.size, 0);
  assert.equal(views[0].visible, false);
  assert.deepEqual(views[0].bounds, bounds);
  pool.setPaneBounds({ x: 0, y: 0, width: 0, height: 0 });
  pool.showPane({ x: 0, y: 0, width: 0, height: 0 });
  assert.equal(host.children.size, 0);
  assert.deepEqual(views[0].bounds, bounds);
  pool.showPane(bounds);
  const replacementHost = hostFixture();
  pool.setHostWindow(replacementHost);
  assert.equal(host.children.size, 0);
  assert.deepEqual([...replacementHost.children], [views[0]]);
  pool.setHostWindow(null);
  assert.equal(replacementHost.children.size, 0);
  assert.equal(views[0].visible, false);
  pool.destroyAll();
});
