const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { createRequire } = require('node:module');
const electron = require('electron');
const { app, BrowserWindow, nativeImage } = electron;
const desktop = path.resolve(__dirname, '../..');
const dependency = createRequire(path.join(desktop, 'package.json'));
const ts = dependency('typescript');
const dom = fs.readFileSync(path.join(desktop, '../../crates/adapters-browser/assets/facade-dom.js'), 'utf8');
app.setPath('userData', process.env.AGISTACK_IAB_TEST_PROFILE);
const html = `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#3468db;color:white;font:20px sans-serif}main{padding:32px}input,button{font:inherit;padding:10px}output{display:block;margin-top:20px}#cover{position:fixed;inset:0;background:green;display:none;z-index:10}</style><main><form><label>QA text <input id="text"></label><button id="save">Save QA text</button></form><output id="result">Not saved</output></main><div id="cover"></div><script>window.events=[];for(const type of ['mousedown','mouseup','click'])document.addEventListener(type,e=>events.push({type,target:e.target.id,trusted:e.isTrusted}));document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();result.textContent=text.value+'|trusted='+e.isTrusted;});</script>`;
const cache = new Map();
function load(name) {
  if (!name.startsWith('./')) return dependency(name);
  const file = path.join(desktop, 'electron/main/iab', name.slice(2) + '.ts');
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} };
  cache.set(file, module);
  const source = fs.readFileSync(name === './viewPool' && process.env.AGISTACK_IAB_VIEW_POOL_SOURCE || file, 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  new Function('require', 'exports', 'module', '__dirname', compiled)(name => name === 'electron' ? electron : load(name), module.exports, module, path.dirname(file));
  return module.exports;
}
async function main() {
  await app.whenReady();
  if (process.platform === 'darwin') app.setActivationPolicy('prohibited');
  const server = http.createServer((_request, response) => { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end(html); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let focusEvents = 0;
  let showEvents = 0;
  const windows = [];
  app.on('browser-window-created', (_event, window) => {
    windows.push(window);
    window.on('focus', () => { focusEvents++; });
    window.on('show', () => { showEvents++; });
  });
  const host = new BrowserWindow({ show: false, width: 1200, height: 900, webPreferences: { sandbox: true, contextIsolation: true } });
  const pool = new (load('./viewPool').IabViewPool)({ preloadPath: path.join(__dirname, 'iab-hidden-preload.cjs'), cursorScriptPath: () => path.join(desktop, 'electron/resources/iab-cursor.js') });
  pool.setHostWindow(host);
  const results = [];
  const url = `http://127.0.0.1:${server.address().port}/`;
  async function check(tab, label) {
    async function evaluate(expression) {
      const reply = await pool.executeCdp(tab, 'Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (reply.exceptionDetails) throw Error(reply.exceptionDetails.exception?.description ?? reply.exceptionDetails.text);
      return reply.result.value;
    }
    const invoke = (method, args) => evaluate(`(${dom})(${JSON.stringify({ operation: 'playwright.locator', args: [[{ kind: 'getByRole', args: method === 'fill' ? ['textbox', { name: 'QA text', exact: true }] : ['button', { name: 'Save QA text', exact: true }] }], method, args] })})`);
    const viewport = await evaluate('({width:innerWidth,height:innerHeight,visibility:document.visibilityState})');
    assert.ok(viewport.width > 0 && viewport.height > 0, `hidden viewport: ${JSON.stringify(viewport)}`);
    assert.equal(host.contentView.children.length, 0);
    assert.equal(pool.browserVisible, false);
    await invoke('fill', [label]);
    // The Rust input_visibility tests verify that the public host owns this scope,
    // including restoration on errors, cancellation and concurrent raw CDP input.
    await pool.executeCdp(tab, 'Emulation.setFocusEmulationEnabled', { enabled: true });
    try {
      await evaluate('events=[]');
      const point = await invoke('clickPoint', [{}]);
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
        await pool.executeCdp(tab, 'Input.dispatchMouseEvent', { type, ...point, button: 'left', clickCount: 1 });
      }
      assert.equal(await evaluate('result.textContent'), `${label}|trusted=true`);
      const events = await evaluate('events');
      assert.deepEqual(events.map(event => event.type), ['mousedown', 'mouseup', 'click']);
      assert.ok(events.every(event => event.trusted && event.target === 'save'));
      await evaluate("document.querySelector('#cover').style.display='block'");
      await assert.rejects(invoke('clickPoint', [{}]), /disabled or obscured/);
      assert.equal((await evaluate('events')).length, 3);
      await evaluate("document.querySelector('#cover').style.display='none'");
    } finally {
      await pool.executeCdp(tab, 'Emulation.setFocusEmulationEnabled', { enabled: false });
    }
    const screenshot = await pool.executeCdp(tab, 'Page.captureScreenshot', { format: 'jpeg', quality: 80 });
    const bytes = Buffer.from(screenshot.data, 'base64');
    assert.equal(bytes.subarray(0, 2).toString('hex'), 'ffd8');
    const image = nativeImage.createFromBuffer(bytes);
    const size = image.getSize();
    assert.ok(size.width > 0 && size.height > 0 && bytes.length > 500);
    const pixel = [...image.toBitmap().subarray(0, 3)];
    assert.ok(Math.max(...pixel) - Math.min(...pixel) > 60, 'screenshot must contain the colored page');
    assert.equal(host.isVisible(), false);
    assert.equal(host.isFocused(), false);
    results.push({ label, viewport, screenshot: size, bytes: bytes.length });
  }
  try {
    const first = await pool.createTab(url);
    const second = await pool.createTab(url);
    await check(first, 'HIDDEN_FIRST');
    await check(second, 'HIDDEN_INACTIVE');
    pool.showPane({ x: 20, y: 40, width: 850, height: 620 });
    assert.equal(host.contentView.children.length, 1);
    pool.hidePane();
    await check(first, 'HIDDEN_AFTER_PANE');
    await pool.setViewport({ width: 640, height: 480 });
    await check(first, 'HIDDEN_OVERRIDE');
    await pool.setViewport(null);
    await check(first, 'HIDDEN_RESET');
    pool.setHostWindow(null);
    const third = await pool.createTab(url);
    await check(third, 'HIDDEN_WITHOUT_HOST');
    assert.equal(windows.length, 4);
    assert.ok(windows.filter(window => window !== host).every(window => window.isDestroyed()));
    assert.equal(BrowserWindow.getAllWindows().length, 1);
    assert.equal(focusEvents, 0);
    assert.equal(showEvents, 0);
    console.log(JSON.stringify({ electron: process.versions.electron, focusEvents, showEvents, temporaryWindowsDestroyed: windows.length - 1, results }));
  } finally {
    pool.destroyAll();
    host.destroy();
    await new Promise(resolve => server.close(resolve));
  }
}
main().then(() => app.exit(0), error => { console.error(error.stack); app.exit(1); });
