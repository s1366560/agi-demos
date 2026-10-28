import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const output = ts.transpileModule(readFileSync(file, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('exports', 'module', 'require', output)(module.exports, module,
    name => name.startsWith('.') ? load(resolve(dirname(file), name + '.ts')) : require(name));
  return module.exports;
}
const main = fileURLToPath(new URL('../electron/main/', import.meta.url));
const { SidecarSupervisor } = load(join(main, 'sidecarSupervisor.ts'));
const { McpAppFrameHost } = load(join(main, 'mcpAppFrameHost.ts'));
const tabId = 'mcpapp-12345678-1234-1234-1234-123456789012';
const mountNonce = 'mcpapp-22345678-1234-1234-1234-123456789012';
const args = { tabId, mountNonce, operation: 'tools/call', arguments: { name: 'increment' } };
const source = String.raw`#!/usr/bin/env node
const {createHmac} = require('node:crypto');
const {appendFileSync} = require('node:fs');
const input = require('node:readline').createInterface({input:process.stdin});
const send = value => process.stdout.write(JSON.stringify(value)+'\n');
const pending = new Map(); let executions = 0;
function release(){
 for(const item of pending.values()){executions++;send({type:'response',id:item.id,ok:true,result:{content:[{type:'text',text:'done'}]}});}
 pending.clear();return {executions};
}
const server=require('node:http').createServer((req,res)=>{res.setHeader('content-type','application/json');res.end(JSON.stringify(release()));});
input.once('line', line => {
 const init=JSON.parse(line), apiToken='fixture-token';
 server.listen(0,'127.0.0.1',()=>{
  const apiBaseUrl='http://127.0.0.1:'+server.address().port;
  const proof=createHmac('sha256',Buffer.from(init.secret,'base64url')).update([init.protocolVersion,init.nonce,process.pid,apiBaseUrl,apiToken].join('\n')).digest('base64url');
  setTimeout(()=>send({type:'ready',protocolVersion:init.protocolVersion,nonce:init.nonce,pid:process.pid,apiBaseUrl,apiToken,proof}),Number(process.env.READY_DELAY||0));
 });
 input.on('line', line => {
  const request=JSON.parse(line); appendFileSync(process.env.AUDIT,JSON.stringify(request)+'\n');
  const reply=result=>send({type:'response',id:request.id,ok:true,result});
  if(request.command==='mcp_app_operation'&&request.args.operation==='tools/call'){pending.set(request.id,request);return;}
  if(request.command==='mcp_app_operation_cancel'){
   // Production may finish the original task before its cancel ack is written.
   send({type:'response',id:request.args.requestId,ok:false,error:'fixture original cancelled before acknowledgement'});
   if(process.env.CANCEL_MODE==='drop')return;
   setTimeout(()=>{
    const target=pending.get(request.args.requestId);
    const exact=target&&target.args.tabId===request.args.tabId&&target.args.mountNonce===request.args.mountNonce;
    if(exact)pending.delete(target.id); reply({cancelled:!!exact});
   },Number(process.env.CANCEL_DELAY||0));return;
  }
  if(request.command==='fixture_release'){
   reply(release());return;
  }
  if(request.command==='fixture_never')return;
  reply({pending:pending.size,executions});
 });
});
input.on('close',()=>process.exit(0));
`;
async function fixture(t, environment = {}, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'agistack-mcp-callback-test-'));
  const binaryPath = join(root, 'sidecar.cjs'), audit = join(root, 'audit.jsonl');
  await writeFile(binaryPath, source); await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({ binaryPath, workspaceCoreBinaryPath: binaryPath,
    dataDirectory: join(root, 'data'), workspaceRoot: root, legacyDataDirectories: [],
    requestTimeoutMs: 40, handshakeTimeoutMs: 2000, shutdownTimeoutMs: 500,
    environment: { AUDIT: audit, ...environment },
    ...options,
  });
  t.after(async () => { await supervisor.stop(); await rm(root, { recursive: true, force: true }); });
  return { supervisor, audit: async () => (await readFile(audit, 'utf8').catch(() => '')).trim().split('\n').filter(Boolean).map(JSON.parse) };
}
test('validated callback waits past ordinary timeout while status remains responsive', async t => {
  const f = await fixture(t); await f.supervisor.start();
  const controller = new AbortController();
  const callback = f.supervisor.invokeCancellable('mcp_app_operation', args, controller.signal);
  await delay(90);
  assert.equal((await f.supervisor.invoke('local_runtime_status')).pending, 1);
  await f.supervisor.invoke('fixture_release');
  assert.deepEqual(await callback, { content: [{ type: 'text', text: 'done' }] });
  await assert.rejects(f.supervisor.invoke('fixture_never'), /timed out/);
});
test('abort cancels the exact private transport and prevents late dispatch', async t => {
  const f = await fixture(t); await f.supervisor.start();
  const controller = new AbortController();
  const callback = f.supervisor.invokeCancellable('mcp_app_operation', args, controller.signal);
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  await delay(0); // Let ready-call microtasks enqueue the callback before the status barrier.
  assert.equal((await f.supervisor.invoke('local_runtime_status')).pending, 1);
  controller.abort(); await rejected;
  const result = await f.supervisor.invoke('fixture_release'); assert.equal(result.executions, 0);
  const audit = await f.audit(), original = audit.find(item => item.command === 'mcp_app_operation');
  const cancellation = audit.find(item => item.command === 'mcp_app_operation_cancel');
  assert.deepEqual(cancellation.args, { requestId: original.id, tabId, mountNonce });
});
test('pre-aborted and handshake-time cancellation cannot send a late callback', async t => {
  const f = await fixture(t, { READY_DELAY: '100' });
  const before = new AbortController(); before.abort();
  await assert.rejects(f.supervisor.invokeCancellable('mcp_app_operation', args, before.signal), { name: 'AbortError' });
  const during = new AbortController();
  const callback = f.supervisor.invokeCancellable('mcp_app_operation', args, during.signal);
  const rejected = assert.rejects(callback, { name: 'AbortError' }); during.abort(); await rejected;
  await f.supervisor.start();
  assert.equal((await f.audit()).some(item => item.command === 'mcp_app_operation'), false);
});
test('stop rejects a retained callback and removes its abort listener', async t => {
  const f = await fixture(t); await f.supervisor.start();
  const controller = new AbortController();
  const callback = f.supervisor.invokeCancellable('mcp_app_operation', args, controller.signal);
  const rejected = assert.rejects(callback, /stopped/);
  await f.supervisor.invoke('local_runtime_status'); await f.supervisor.stop(); await rejected;
  controller.abort(); assert.equal((await f.audit()).some(item => item.command.endsWith('_cancel')), false);
});
test('host cancellation waits for private acknowledgement before immediate independent HTTP resume', async t => {
  const f = await fixture(t, { CANCEL_DELAY: '70' }, { requestTimeoutMs: 500 });
  const identity = await f.supervisor.start();
  const frame = { tabId, frameName: mountNonce };
  const host = new McpAppFrameHost({ requireCurrentMount: () => frame, isCurrent: () => true },
    input => f.supervisor.invoke('mcp_app_operation', input),
    (input, signal) => f.supervisor.invokeCancellable('mcp_app_operation', input, signal));
  const { operationId } = host.prepare(args);
  const callback = host.operation({ ...args, operationId });
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  await delay(0); assert.equal((await f.supervisor.invoke('local_runtime_status')).pending, 1);
  const cancellation = await host.cancel({ ...args, operationId });
  assert.equal(cancellation.cancelled, true);
  const resumed = await fetch(identity.apiBaseUrl + '/resume');
  assert.equal((await resumed.json()).executions, 0);
  await rejected;
});
test('missing cancel acknowledgement is unknown despite an early original cancellation response', async t => {
  const f = await fixture(t, { CANCEL_MODE: 'drop' }); await f.supervisor.start();
  const frame = { tabId, frameName: mountNonce };
  const host = new McpAppFrameHost({ requireCurrentMount: () => frame, isCurrent: () => true },
    input => f.supervisor.invoke('mcp_app_operation', input),
    (input, signal) => f.supervisor.invokeCancellable('mcp_app_operation', input, signal));
  const { operationId } = host.prepare(args);
  const callback = host.operation({ ...args, operationId });
  const rejected = assert.rejects(callback, error => error.name === 'AbortError' && error.cancellationConfirmed === false);
  await delay(0); assert.equal((await f.supervisor.invoke('local_runtime_status')).pending, 1);
  assert.deepEqual(await host.cancel({ ...args, operationId }), { cancelled: false, outcome: 'unknown' });
  await rejected;
  assert.equal((await f.supervisor.invoke('local_runtime_status')).pending, 1);
});
function hostFixture() {
  let current = { tabId, frameName: mountNonce };
  const dispatches = [];
  const frames = {
    requireCurrentMount(input) { if (!current || input?.tabId !== current.tabId || input.mountNonce !== current.frameName) throw Error('mcp_app_frame_expired'); return current; },
    isCurrent(mount) { return current === mount; },
    cancel(mount) { if (current?.frameName === mount.frameName) current = null; return mount; },
    clear() { const retired = current ? [current] : []; current = null; return retired; },
  };
  const host = new McpAppFrameHost(frames, async input => ({ operation: input.operation }), (input, signal) => {
    dispatches.push({ input, signal });
    return new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true });
    });
  });
  return { host, dispatches, replace(nonce) { current = { tabId, frameName: nonce }; } };
}
test('host prepare does not dispatch and cancellation before execute never dispatches', async () => {
  const f = hostFixture(); const prepared = f.host.prepare(args);
  assert.equal(typeof prepared.operationId, 'string'); assert.equal(f.dispatches.length, 0);
  await f.host.cancel({ ...args, operationId: prepared.operationId });
  await assert.rejects(f.host.operation({ ...args, operationId: prepared.operationId }), /unavailable|cancelled/);
  assert.equal(f.dispatches.length, 0);
});
test('host bounds all prepared and running callbacks before registering another', async () => {
  const f = hostFixture();
  const prepared = Array.from({ length: 32 }, () => f.host.prepare(args));
  assert.throws(() => f.host.prepare(args), /busy/);
  assert.equal(f.dispatches.length, 0);
  await f.host.cancel({ ...args, operationId: prepared[0].operationId });
  assert.equal(typeof f.host.prepare(args).operationId, 'string');
  await f.host.clear();
});
for (const action of ['unregister', 'clear']) test('host ' + action + ' aborts active callback', async () => {
  const f = hostFixture(); const prepared = f.host.prepare(args);
  const callback = f.host.operation({ ...args, operationId: prepared.operationId });
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  await (action === 'clear' ? f.host.clear() : f.host.unregister({ tabId, frameName: mountNonce }));
  await rejected; assert.equal(f.dispatches[0].signal.aborted, true);
});
test('late old mount cancellation cannot affect a new same-business callback', async () => {
  const f = hostFixture(); const old = f.host.prepare(args);
  await f.host.unregister({ tabId, frameName: mountNonce });
  const nextNonce = 'mcpapp-32345678-1234-1234-1234-123456789012'; f.replace(nextNonce);
  const nextArgs = { ...args, mountNonce: nextNonce }, next = f.host.prepare(nextArgs);
  const callback = f.host.operation({ ...nextArgs, operationId: next.operationId });
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  await f.host.cancel({ ...args, operationId: old.operationId });
  await assert.rejects(f.host.cancel({ ...args, operationId: next.operationId }), /expired/);
  assert.equal(f.dispatches[0].signal.aborted, false);
  await f.host.cancel({ ...nextArgs, operationId: next.operationId }); await rejected;
});
