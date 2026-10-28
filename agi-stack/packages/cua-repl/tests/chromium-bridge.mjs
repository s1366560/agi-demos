// Real Chromium/CDP fixture for adapters-browser integration tests.
import { createRequire } from 'node:module';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { WebSocket, WebSocketServer } from 'ws';
const require = createRequire(new URL('../../../apps/desktop/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const profile = await mkdtemp(join(tmpdir(), 'memstack-facade-chromium-'));
const pageServer = http.createServer((request, response) => {
  response.setHeader('content-type', 'text/html');
  if (request.url === '/download') { response.setHeader('content-type', 'text/plain'); response.setHeader('content-disposition', 'attachment; filename="fixture.txt"'); response.end('download fixture\n'); }
  else if (request.url === '/files') response.end('<input type="file" aria-label="Upload" onchange="document.querySelector(\'output\').textContent=this.files[0]?.name"><output></output>');
  else if (request.url === '/files-frame') response.end(`<iframe id="foreign" src="http://localhost:${pageServer.address().port}/files"></iframe><a download href="/download">Download</a>`);
  else if (request.url === '/media.txt') { response.setHeader('content-type', 'text/plain'); response.end('media fixture\n'); }
  else if (request.url === '/media') response.end('<a href="/media.txt" download="fixture-media.txt">Media file</a><img alt="Inline media" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY1kAAAAASUVORK5CYII=">');
  else if (request.url === '/auth') response.end('<form method="post" action="/auth-finished"><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">Sign in</button></form>');
  else if (request.url === '/auth-finished') { request.resume(); response.end('<p data-auth-result="complete">Authentication fixture finished</p>'); }
  else if (request.url === '/frame') response.end('<label>Frame value<input aria-label="Frame value"></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Save frame</button><output></output>');
  else response.end(`<label>Account<input aria-label="Account"></label><button onclick="document.querySelector('output').textContent=document.querySelector('input').value">Save</button><output></output><iframe id="foreign" src="http://localhost:${pageServer.address().port}/frame"></iframe>`);
});
await new Promise(resolve => pageServer.listen(0, '0.0.0.0', resolve));
const browser = spawn(chromium.executablePath(), ['--headless=new', '--no-sandbox', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--site-per-process', '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: ['ignore', 'ignore', 'inherit'] });
let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  browser.kill('SIGTERM');
  await new Promise(resolve => browser.once('exit', resolve));
  pageServer.close();
  await rm(profile, { recursive: true, force: true });
  process.exit(0);
}
process.on('SIGTERM', () => void close());
process.on('SIGINT', () => void close());
let endpoint;
for (let attempt = 0; attempt < 500; attempt++) {
  try { const [port, path] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).trim().split('\n'); endpoint = `ws://127.0.0.1:${port}${path}`; break; } catch { await new Promise(resolve => setTimeout(resolve, 20)); }
}
if (!endpoint) throw new Error('Chromium CDP endpoint did not start');
const cdp = new WebSocket(endpoint);
await new Promise((resolve, reject) => { cdp.once('open', resolve); cdp.once('error', reject); });
const waiting = new Map();
let nextId = 0;
let peer;
const rootTargets = new Map();
function send(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    waiting.set(id, { resolve, reject });
    cdp.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}
cdp.on('message', data => {
  const message = JSON.parse(data);
  if (message.id) {
    const pending = waiting.get(message.id); waiting.delete(message.id);
    if (message.error) pending?.reject(new Error(message.error.message)); else pending?.resolve(message.result);
  } else if (message.method && peer?.readyState === WebSocket.OPEN) {
    const root = [...rootTargets.entries()].find(([, info]) => info.sessionId === message.sessionId);
    const tabId = root?.[0] ?? 1;
    peer.send(JSON.stringify({ jsonrpc: '2.0', method: 'onCDPEvent', params: { tabId, method: message.method, params: message.params, ...(!root && message.sessionId ? { sessionId: message.sessionId } : {}) } }));
  }
});
const url = `http://127.0.0.1:${pageServer.address().port}/`;
const created = await send('Target.createTarget', { url });
rootTargets.set(1, { targetId: created.targetId });
const bridge = new WebSocketServer({ host: '127.0.0.1', port: 0 });
await new Promise(resolve => bridge.once('listening', resolve));
bridge.on('connection', socket => {
  peer = socket;
  socket.on('message', async data => {
    const request = JSON.parse(data); const params = request.params ?? {};
    try {
      let result;
      if (request.method === 'getTabs') {
        const targets = await send('Target.getTargets');
        result = { tabs: [...rootTargets.entries()].map(([tabId, info]) => ({ tabId, windowId: 1, active: tabId === 1, ...targets.targetInfos.find(target => target.targetId === info.targetId) })) };
      } else if (request.method === 'attach') {
        const info = rootTargets.get(params.tabId);
        if (!info.sessionId) info.sessionId = (await send('Target.attachToTarget', { targetId: info.targetId, flatten: true })).sessionId;
        result = {};
      } else if (request.method === 'executeCdp') {
        const info = rootTargets.get(params.tabId);
        result = { result: await send(params.method, params.params, params.sessionId ?? info.sessionId) };
      } else if (request.method === 'facadeCapabilities') result = { browser: [], tab: ['cdp', 'pageAssets', 'webmcp'] };
      else if (request.method === 'moveMouse' || request.method === 'turnEnded') result = {};
      else throw new Error(`unsupported fixture method ${request.method}`);
      socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }));
    } catch (error) { socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id, error: { code: -32000, message: error.message } })); }
  });
});
process.stdout.write(`${JSON.stringify({ endpoint: `ws://127.0.0.1:${bridge.address().port}/`, url })}\n`);
