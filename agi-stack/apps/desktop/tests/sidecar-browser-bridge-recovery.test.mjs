import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const modules = new Map();
function load(url) {
  if (modules.has(url.href)) return modules.get(url.href);
  const module = { exports: {} };
  modules.set(url.href, module.exports);
  const source = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'exports', source)((name) => name.startsWith('.')
    ? load(new URL(`${name}.ts`, url)) : require(name), module.exports);
  return module.exports;
}
const { SidecarSupervisor } = load(new URL('../electron/main/sidecarSupervisor.ts', import.meta.url));

const bridge = (enabled, fullCdp = false) => ({
  enabled, port: 9765, extension_ids: ['owned-extension'], full_cdp_access_enabled: fullCdp,
  cdp_endpoints: [], default_browser_id: 'iab',
});
const source = String.raw`#!/usr/bin/env node
const { createHmac } = require('node:crypto');
const { appendFileSync, readFileSync } = require('node:fs');
const readline = require('node:readline');
const audit = (event) => appendFileSync(process.env.FIXTURE_AUDIT, JSON.stringify(event) + '\n');
appendFileSync(process.env.FIXTURE_STARTS, 'started\n');
const generation = readFileSync(process.env.FIXTURE_STARTS, 'utf8').trim().split('\n').length;
let config = { workspace_root: '', browser_bridge: {
  enabled: false, port: 9765, extension_ids: [], full_cdp_access_enabled: false,
}};
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const send = (value) => process.stdout.write(JSON.stringify(value) + '\n');
input.once('line', (line) => {
  const initial = JSON.parse(line);
  const apiBaseUrl = 'http://127.0.0.1:' + (42000 + generation);
  const apiToken = 'fixture-token-' + generation;
  const proof = createHmac('sha256', Buffer.from(initial.secret, 'base64url'))
    .update([initial.protocolVersion, initial.nonce, process.pid, apiBaseUrl, apiToken].join('\n'))
    .digest('base64url');
  const ready = () => {
    send({type: 'ready', protocolVersion: initial.protocolVersion, nonce: initial.nonce,
      pid: process.pid, apiBaseUrl, apiToken, proof});
    input.on('line', (line) => {
    const request = JSON.parse(line);
    audit({generation, command: request.command, args: request.args});
    if (request.command === 'fixture_crash') process.exit(19);
    const configure = request.command === 'local_runtime_configure';
    const restoring = configure && generation > 1 && !request.args?.fixture;
    const mode = restoring ? process.env.FIXTURE_RECOVERY_MODE : '';
    const respond = () => {
      if (request.args?.fixture?.fail || mode === 'fail') {
        send({type: 'response', id: request.id, ok: false, error: 'fixture rejected config'});
        return;
      }
      if (configure) config = {...config, ...request.args.config};
      const result = {generation, config};
      if (mode === 'mismatch') result.config = {...config,
        browser_bridge: {...config.browser_bridge, enabled: !config.browser_bridge.enabled}};
      if (mode === 'provider-mismatch') result.config = {...config,
        browser_bridge: {...config.browser_bridge, cdp_endpoints: []}};
      send({type: 'response', id: request.id, ok: true, result});
    };
    if (mode === 'timeout') return;
    setTimeout(respond, request.args?.fixture?.delay ?? (restoring
      ? Number(process.env.FIXTURE_RECOVERY_DELAY || 0) : 0));
    });
  };
  setTimeout(ready, Number(process.env.FIXTURE_READY_DELAY || 0));
});
input.on('close', () => setTimeout(() => process.exit(0),
  Number(process.env.FIXTURE_SHUTDOWN_DELAY || 0)));
`;

async function fixture(options = {}, environment = {}) {
  const root = await mkdtemp(join(tmpdir(), 'agistack-bridge-recovery-test-'));
  const binaryPath = join(root, 'sidecar.cjs');
  const auditPath = join(root, 'audit.jsonl');
  const startsPath = join(root, 'starts.txt');
  await writeFile(binaryPath, source);
  await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath, workspaceCoreBinaryPath: binaryPath, dataDirectory: join(root, 'data'),
    workspaceRoot: root, legacyDataDirectories: [], restartDelaysMs: [1],
    maxRestartAttempts: 3, requestTimeoutMs: 500, handshakeTimeoutMs: 2000,
    shutdownTimeoutMs: 1000,
    environment: {FIXTURE_AUDIT: auditPath, FIXTURE_STARTS: startsPath, ...environment},
    ...options,
  });
  const calls = async () => (await readFile(auditPath, 'utf8').catch(() => ''))
    .trim().split('\n').filter(Boolean).map((line) => JSON.parse(line));
  const configure = (value, extra = {}) => supervisor.invoke('local_runtime_configure', {
    config: {workspace_root: root, browser_bridge: value}, fixture: {}, ...extra,
  });
  return {supervisor, calls, configure,
    async starts() {return (await readFile(startsPath, 'utf8').catch(() => '')).trim().split('\n').filter(Boolean).length;},
    async close() {await supervisor.stop(); await rm(root, {recursive: true, force: true});},
  };
}

async function waitFor(check) {
  const limit = Date.now() + 3000;
  while (!await check()) {
    if (Date.now() >= limit) throw new Error('fixture condition timed out');
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

async function crash(supervisor) {
  await assert.rejects(supervisor.invoke('fixture_crash'), /sidecar exited unexpectedly/);
}

for (const enabled of [true, false]) {
  test(`sidecar restores only the acknowledged bridge configuration: enabled=${enabled}`, async () => {
    let recovered = 0;
    const f = await fixture({onRecovered: () => recovered++});
    try {
      const expected = bridge(enabled, enabled);
      await f.configure(expected);
      await f.supervisor.invoke('computer_use_cloud_v2', {input: {action: 'call', request_id: 'expired'}});
      await crash(f.supervisor);
      const status = await f.supervisor.invoke('local_runtime_status');
      assert.deepEqual(status.config.browser_bridge, expected);
      assert.equal(recovered, 1);
      const calls = (await f.calls()).filter((call) => call.generation === 2);
      assert.equal(calls[0].command, 'local_runtime_configure');
      assert.deepEqual(calls[0].args, {config: {browser_bridge: expected}});
      assert.deepEqual(calls.map((call) => call.command), ['local_runtime_configure', 'local_runtime_status']);
    } finally {await f.close();}
  });
}

test('a supervisor with no confirmed bridge choice never enables or replays bridge config', async () => {
  const f = await fixture();
  try {
    await f.supervisor.invoke('local_runtime_configure', {config: {workspace_root: 'owned-workspace'}});
    await crash(f.supervisor);
    assert.equal((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge.enabled, false);
    assert.equal((await f.calls()).filter((call) => call.generation === 2 &&
      call.command === 'local_runtime_configure').length, 0);
  } finally {await f.close();}
});

test('acknowledged CDP endpoints and stable default survive restart without adopting caller mutations', async () => {
  const f = await fixture();
  try {
    const config = bridge(true);
    config.cdp_endpoints = [{ id: '23344bba-c174-42a5-a14d-0534978df6c2', name: 'Local', endpoint: 'ws://127.0.0.1:9222/devtools/browser/owned', enabled: true }];
    config.default_browser_id = `cdp:${config.cdp_endpoints[0].id}`;
    const expected = structuredClone(config);
    const configured = f.configure(config);
    config.cdp_endpoints[0].endpoint = 'http://127.0.0.1:3333';
    await configured;
    await crash(f.supervisor);
    assert.deepEqual((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge, expected);
  } finally { await f.close(); }
});

test('an unsuccessful disable invalidates an older enable instead of replaying it after a crash', async () => {
  const f = await fixture();
  try {
    await f.configure(bridge(true));
    await assert.rejects(f.configure(bridge(false), {fixture: {fail: true}}), /fixture rejected/);
    await crash(f.supervisor);
    assert.equal((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge.enabled, false);
    assert.equal((await f.calls()).filter((call) => call.generation === 2 &&
      call.command === 'local_runtime_configure').length, 0);
  } finally {await f.close();}
});

test('concurrent configure calls are serialized and only the latest acknowledged choice is restored', async () => {
  const f = await fixture();
  try {
    const first = f.configure(bridge(true), {fixture: {delay: 60}});
    const second = f.configure(bridge(false));
    await Promise.all([first, second]);
    await crash(f.supervisor);
    assert.deepEqual((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge, bridge(false));
    assert.deepEqual((await f.calls()).filter((call) => call.command === 'local_runtime_configure')
      .map((call) => call.args.config.browser_bridge.enabled), [true, false, false]);
  } finally {await f.close();}
});

test('a configure interrupted with its old process cannot replace the new process choice', async () => {
  const f = await fixture();
  try {
    const old = f.configure(bridge(true), {fixture: {delay: 200}});
    const rejected = assert.rejects(old, /sidecar exited unexpectedly/);
    await waitFor(async () => (await f.calls()).some((call) => call.command === 'local_runtime_configure'));
    await crash(f.supervisor);
    await rejected;
    await f.configure(bridge(false));
    await crash(f.supervisor);
    assert.deepEqual((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge, bridge(false));
  } finally {await f.close();}
});

test('readiness is hidden until restore finishes and a concurrent disable fences an in-flight enable', async () => {
  let recovered = 0;
  const f = await fixture({onRecovered: () => recovered++}, {FIXTURE_RECOVERY_DELAY: '80'});
  try {
    await f.configure(bridge(true, true));
    await crash(f.supervisor);
    const status = f.supervisor.invoke('local_runtime_status');
    await waitFor(async () => (await f.calls()).some((call) => call.generation === 2));
    assert.equal(f.supervisor.identity, null);
    assert.equal(recovered, 0);
    const disabled = f.configure(bridge(false));
    const firstPublicStatus = await status;
    assert.equal(firstPublicStatus.config.browser_bridge.enabled, false);
    assert.equal(firstPublicStatus.config.browser_bridge.full_cdp_access_enabled, false);
    await disabled;
    const calls = (await f.calls()).filter((call) => call.generation === 2);
    assert.deepEqual(calls.slice(0, 2).map((call) => call.args.config.browser_bridge.enabled), [true, false]);
    await crash(f.supervisor);
    assert.deepEqual((await f.supervisor.invoke('local_runtime_status')).config.browser_bridge, bridge(false));
  } finally {await f.close();}
});

for (const mode of ['fail', 'mismatch', 'timeout', 'provider-mismatch']) {
  test(`failed recovery never publishes an identity or recovery notification: ${mode}`, async () => {
    let recovered = 0;
    const f = await fixture({onRecovered: () => recovered++, maxRestartAttempts: 0, requestTimeoutMs: 60},
      {FIXTURE_RECOVERY_MODE: mode});
    try {
      const config = bridge(true);
      config.cdp_endpoints = [{ id: '23344bba-c174-42a5-a14d-0534978df6c2', name: 'Local', endpoint: 'http://127.0.0.1:9222', enabled: true }];
      config.default_browser_id = `cdp:${config.cdp_endpoints[0].id}`;
      await f.configure(config);
      // Explicit stop/start isolates one recovery attempt without automatic retries.
      await f.supervisor.stop();
      await assert.rejects(f.supervisor.start(), /fixture rejected|not confirmed|timed out/);
      assert.equal(f.supervisor.identity, null);
      assert.equal(recovered, 0);
    } finally {await f.close();}
  });
}

test('shutdown rejects queued configuration without restarting a stopped supervisor', async () => {
  const f = await fixture();
  try {
    const first = f.configure(bridge(true), {fixture: {delay: 200}});
    const second = f.configure(bridge(false));
    const outcomes = Promise.allSettled([first, second]);
    await waitFor(async () => (await f.calls()).length > 0);
    await f.supervisor.stop();
    assert.deepEqual((await outcomes).map((value) => value.status), ['rejected', 'rejected']);
    assert.equal(f.supervisor.identity, null);
    assert.ok((await f.calls()).every((call) => call.generation === 1));
  } finally {await f.close();}
});

test('shutdown during recovery does not resurrect a process or emit a recovered event', async () => {
  let recovered = 0;
  const f = await fixture({onRecovered: () => recovered++}, {FIXTURE_RECOVERY_DELAY: '200'});
  try {
    await f.configure(bridge(true));
    await crash(f.supervisor);
    const waiting = f.supervisor.invoke('local_runtime_status');
    const rejected = assert.rejects(waiting, /sidecar stopped|sidecar is unavailable/);
    await waitFor(async () => (await f.calls()).some((call) => call.generation === 2));
    await f.supervisor.stop();
    await rejected;
    assert.equal(f.supervisor.identity, null);
    assert.equal(recovered, 0);
    assert.ok((await f.calls()).every((call) => call.generation <= 2));
  } finally {await f.close();}
});

test('a valid delayed handshake after shutdown cannot publish an old process identity', async () => {
  const f = await fixture({}, {FIXTURE_READY_DELAY: '60', FIXTURE_SHUTDOWN_DELAY: '150'});
  try {
    const starting = f.supervisor.start();
    const rejected = assert.rejects(starting, /sidecar stopped/);
    await waitFor(async () => await f.starts() === 1);
    await f.supervisor.stop();
    await rejected;
    assert.equal(f.supervisor.identity, null);
    assert.equal(await f.starts(), 1);
    assert.deepEqual(await f.calls(), []);
  } finally {await f.close();}
});

test('a late old-process exit cannot clear a new explicitly started process identity', async () => {
  const f = await fixture({}, {FIXTURE_SHUTDOWN_DELAY: '150'});
  try {
    const old = await f.supervisor.start();
    const stopping = f.supervisor.stop();
    const current = await f.supervisor.start();
    await stopping;
    assert.notEqual(current.pid, old.pid);
    assert.equal(f.supervisor.identity?.pid, current.pid);
    assert.equal((await f.supervisor.invoke('local_runtime_status')).generation, 2);
  } finally {await f.close();}
});
