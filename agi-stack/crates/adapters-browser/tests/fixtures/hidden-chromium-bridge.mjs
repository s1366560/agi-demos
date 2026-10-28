// Raw signed Chrome/Edge + production extension bridge. Do not use Playwright
// to launch or attach pages: its initialization forces hidden pages visible.
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, readFile, writeFile, readdir, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { spawn, execFileSync } from 'node:child_process';
import http from 'node:http';

const stack = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const require = createRequire(join(stack, 'apps/browser-extension/package.json'));
const ts = require('typescript');
const { WebSocket, WebSocketServer } = createRequire(join(stack, 'packages/cua-repl/package.json'))('ws');
const executable = process.env.AGISTACK_NATIVE_CHROMIUM;
const family = process.env.AGISTACK_NATIVE_BROWSER_FAMILY ?? 'chrome';
if (!['chrome', 'edge'].includes(family)) throw new Error('invalid native browser family');
if (!executable) throw new Error('set AGISTACK_NATIVE_CHROMIUM to the signed Chrome/Edge executable');
const scratch = await mkdtemp(join(tmpdir(), 'memstack-hidden-chromium-'));
const extension = join(scratch, 'extension');
await mkdir(extension);
async function transpile(directory, relative = '') {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    const relativePath = join(relative, entry.name);
    if (entry.isDirectory()) await transpile(path, relativePath);
    else if (entry.name.endsWith('.ts') && !entry.name.endsWith('.test.ts')) {
      const output = join(extension, relativePath.slice(0, -3) + '.js');
      await mkdir(dirname(output), { recursive: true });
      const source = ts.transpileModule(await readFile(path, 'utf8'), {
        compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
      }).outputText.replace(/(from\s+['"])(\.\.?\/[^'"]+)(['"])/g, '$1$2.js$3');
      await writeFile(output, source);
    }
  }
}
await transpile(join(stack, 'apps/browser-extension/src'));
await writeFile(join(extension, 'background.js'), `import {createBridge} from './handlers.js';
globalThis.bridge=createBridge(chrome,${JSON.stringify(family)}); globalThis.events=[];
chrome.debugger.onEvent.addListener((source,method,params)=>events.push({source,method,params}));`);
await writeFile(join(extension, 'manifest.json'), JSON.stringify({
  manifest_version: 3, name: 'Hidden renderer regression', version: '0.0.1',
  permissions: ['debugger', 'tabs', 'scripting', 'storage', 'tabGroups', 'alarms'],
  host_permissions: ['<all_urls>'], background: { service_worker: 'background.js', type: 'module' },
}));
const pageServer = http.createServer((request, response) => {
  response.setHeader('content-type', 'text/html');
  if (request.url === '/frame') response.end('<label>Frame value<input></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Save frame</button><output></output>');
  else response.end(`<style>body{padding:24px}button{padding:12px;margin:20px}</style>
    <label>Account<input></label><button onclick="document.querySelector('output').textContent=document.querySelector('input').value">Save</button><output>Not saved</output>
    <iframe id="foreign" src="http://localhost:${pageServer.address().port}/frame"></iframe>
    <script>globalThis.inputEvents=[];for(const type of ['pointerdown','pointerup','click'])document.addEventListener(type,e=>{inputEvents.push({type,trusted:e.isTrusted});document.body.dataset.inputEvents=JSON.stringify(inputEvents)},true)</script>`);
});
await new Promise(resolve => pageServer.listen(0, '0.0.0.0', resolve));
const browser = spawn(executable, [
  '--remote-debugging-pipe', '--enable-unsafe-extension-debugging', '--use-mock-keychain',
  `--user-data-dir=${join(scratch, 'profile')}`, '--no-first-run', '--no-default-browser-check', 'about:blank',
], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
let closing = false;
let bridge;
let timer;
async function close() {
  if (closing) return;
  closing = true;
  clearInterval(timer);
  if (browser.exitCode === null && browser.signalCode === null) {
    const exited = new Promise(resolve => browser.once('exit', resolve));
    browser.kill('SIGTERM');
    const kill = setTimeout(() => browser.kill('SIGKILL'), 5000);
    await exited; clearTimeout(kill);
  }
  bridge?.close(); pageServer.close();
  await rm(scratch, { recursive: true, force: true });
}
process.on('SIGTERM', () => void close().then(() => process.exit(0)));
process.on('SIGINT', () => void close().then(() => process.exit(0)));
process.on('uncaughtException', error => { console.error(error); void close().then(() => process.exit(1)); });
const waiting = new Map();
let next = 0;
let buffer = '';
browser.stdio[4].setEncoding('utf8');
browser.stdio[4].on('data', chunk => {
  buffer += chunk;
  for (;;) {
    const at = buffer.indexOf('\0'); if (at < 0) break;
    const line = buffer.slice(0, at); buffer = buffer.slice(at + 1); if (!line) continue;
    const message = JSON.parse(line); const pending = waiting.get(message.id);
    if (!pending) continue;
    waiting.delete(message.id); clearTimeout(pending.timer);
    if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
    else pending.resolve(message.result);
  }
});
function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++next;
    const timer = setTimeout(() => { waiting.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    waiting.set(id, { resolve, reject, timer });
    browser.stdio[3].write(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }) + '\0');
  });
}
await send('Extensions.loadUnpacked', { path: extension });
let target;
for (let attempt = 0; attempt < 100; attempt++) {
  target = (await send('Target.getTargets')).targetInfos.find(target => target.type === 'service_worker' && target.url.endsWith('/background.js'));
  if (target) break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
if (!target) throw new Error('extension service worker unavailable');
const session = (await send('Target.attachToTarget', { targetId: target.targetId, flatten: true })).sessionId;
await send('Runtime.enable', {}, session);
await send('Runtime.runIfWaitingForDebugger', {}, session);
async function evaluateWorker(fn, arg) {
  const result = await send('Runtime.evaluate', { expression: `(${fn.toString()})(${JSON.stringify(arg)})`, returnByValue: true, awaitPromise: true }, session);
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
for (let attempt = 0; attempt < 100; attempt++) {
  if (await evaluateWorker(() => !!globalThis.bridge)) break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
async function dispatch(method, params) {
  const response = await evaluateWorker(async ({ method, params }) => globalThis.bridge.dispatch({ jsonrpc: '2.0', id: 1, method, params }), { method, params });
  if (response.error) throw new Error(JSON.stringify(response.error));
  return response.result;
}
const url = `http://127.0.0.1:${pageServer.address().port}/`;
const { tabId } = await dispatch('createTab', { url });
const cdp = (method, params) => dispatch('executeCdp', { tabId, method, params }).then(result => result.result);
await cdp('Page.enable', {});
for (let attempt = 0; attempt < 100; attempt++) {
  if ((await cdp('Runtime.evaluate', { expression: 'document.querySelector("button")!==null', returnByValue: true })).result.value) break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
const { windowId } = await evaluateWorker(tabId => chrome.tabs.get(tabId), tabId);
await evaluateWorker(windowId => chrome.windows.update(windowId, { state: 'minimized' }), windowId);
for (let attempt = 0; attempt < 100; attempt++) {
  if ((await cdp('Runtime.evaluate', { expression: 'document.visibilityState', returnByValue: true })).result.value === 'hidden') break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
const trace = [];
let peer;
let draining = false;
async function flush() {
  if (draining || closing || peer?.readyState !== WebSocket.OPEN) return;
  draining = true;
  try {
    for (const event of await evaluateWorker(() => globalThis.events.splice(0))) {
      peer.send(JSON.stringify({ jsonrpc: '2.0', method: 'onCDPEvent', params: { tabId: 1, method: event.method, params: event.params, ...(event.source.sessionId ? { sessionId: event.source.sessionId } : {}) } }));
    }
  } finally { draining = false; }
}
function foreground() {
  if (process.platform !== 'darwin') return null;
  return execFileSync('/usr/bin/osascript', ['-l', 'JavaScript', '-e', 'ObjC.import("AppKit"); $.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier'], { encoding: 'utf8' }).trim();
}
bridge = new WebSocketServer({ host: '127.0.0.1', port: 0 });
await new Promise(resolve => bridge.once('listening', resolve));
bridge.on('connection', socket => {
  peer = socket;
  socket.on('message', async data => {
    const request = JSON.parse(data); const params = request.params ?? {};
    try {
      let result;
      if (request.method === 'fixtureState') {
        const state = await evaluateWorker(async ({ tabId, windowId }) => ({
          tab: await chrome.tabs.get(tabId), window: await chrome.windows.get(windowId),
          active: (await chrome.tabs.query({ active: true, windowId })).map(tab => tab.id),
        }), { tabId, windowId });
        result = { active: state.active, window: { focused: state.window.focused, state: state.window.state }, targetActive: state.tab.active, foreground: foreground(), trace };
      } else if (request.method === 'getTabs') {
        result = { tabs: (await dispatch('getTabs', {})).tabs.filter(tab => tab.tabId === tabId).map(tab => ({ ...tab, tabId: 1 })) };
      } else if (request.method === 'facadeCapabilities') result = { browser: [], tab: ['cdp', 'pageAssets', 'webmcp'] };
      else if (request.method === 'moveMouse' || request.method === 'turnEnded') result = {};
      else {
        if (request.method === 'executeCdp' && (params.method.startsWith('Input.') || params.method === 'Emulation.setFocusEmulationEnabled')) trace.push({ method: params.method, params: params.params });
        result = await dispatch(request.method, { ...params, tabId });
      }
      await flush();
      socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }));
    } catch (error) { socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id, error: { code: -32000, message: error.message } })); }
  });
});
timer = setInterval(() => void flush().catch(() => {}), 10);
process.stdout.write(JSON.stringify({ endpoint: `ws://127.0.0.1:${bridge.address().port}/`, url, version: await send('Browser.getVersion') }) + '\n');
