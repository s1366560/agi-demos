import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ReplKernel } from '../src/kernel.mjs';

async function retainedModule(t) {
  const root = await mkdtemp(join(tmpdir(), 'cua-repl-reset-contract-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const packageRoot = join(root, 'node_modules', 'retained-app');
  await mkdir(packageRoot, { recursive: true });
  await writeFile(join(packageRoot, 'package.json'), JSON.stringify({ name: 'retained-app', type: 'module', exports: './index.mjs' }));
  await writeFile(join(packageRoot, 'index.mjs'), 'let value; export const remember = item => { value = item; }; export const recall = () => value;');
  return root;
}

test('reset refuses active host work and starts a fresh variable and documentation session after completion', async () => {
  const output = [];
  let complete;
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const repl = new ReplKernel({
    enabledSurfaces: ['computer'], send: value => output.push(value),
    rpc: async (method, params) => {
      assert.equal(method, 'computer.call');
      assert.equal(params.tool, 'computer_list_apps');
      started();
      return new Promise(resolve => { complete = resolve; });
    },
  });
  const active = repl.execute('before', 'let retained = 7; await cua.initialize(); await cua.listApps({emit:false});');
  await ready;
  assert.throws(() => repl.reset(), /cannot reset an active execution/);
  await assert.rejects(repl.execute('overlap', 'retained'), /already active/);
  complete({ apps: [] });
  await active;
  const before = output.filter(value => value.id === 'before');
  assert.equal(before.length, 1);
  assert.equal(repl.reset().generation, 2);
  assert.equal(await repl.execute('after', 'await cua.initialize(); await cua.initialize(); typeof retained'), 'undefined');
  const after = output.filter(value => value.id === 'after');
  assert.equal(after.length, 1);
  assert.equal(after[0].content.text, before[0].content.text);
});

test('media output preserves execution identity and failures neither emit fallback data nor poison later cells', async () => {
  const output = [];
  let rejectOutput = false;
  const repl = new ReplKernel({
    rpc: async () => { throw new Error('media output must not dispatch host tools'); },
    send: value => {
      if (rejectOutput) throw new Error('output sink unavailable');
      output.push(value);
    },
  });
  await repl.execute('media', 'nodeRepl.emitImage({bytes:new Uint8Array([0,1,2]),mimeType:"image/webp"}); nodeRepl.emitAudio({bytes:new Uint8Array([3,4,5])});');
  assert.deepEqual(output, [
    { type: 'output', id: 'media', content: { type: 'image', mimeType: 'image/webp', data: 'AAEC' } },
    { type: 'output', id: 'media', content: { type: 'audio', mimeType: 'audio/wav', data: 'AwQF' } },
  ]);
  await assert.rejects(repl.execute('malformed', 'nodeRepl.emitImage({bytes:{}})'), /Buffer|Array|type|instance/);
  assert.equal(output.length, 2);
  rejectOutput = true;
  await assert.rejects(repl.execute('failed-output', 'nodeRepl.emitAudio({bytes:new Uint8Array([9])})'), /output sink unavailable/);
  rejectOutput = false;
  assert.equal(await repl.execute('recovered', 'nodeRepl.write("recovered"); 42'), 42);
  assert.equal(output.at(-1).id, 'recovered');
  assert.equal(output.at(-1).content.text, 'recovered');
});

test('in-process reset revokes a package-retained app while fresh and same-generation handles work', async t => {
  const root = await retainedModule(t);
  const calls = [];
  const repl = new ReplKernel({
    cwd: root, enabledSurfaces: ['computer'], send() {},
    rpc: async (method, params, id) => {
      calls.push({ method, params, id });
      if (params.tool === 'computer_get_app_state') return { snapshot_id: 'before-reset', window_id: '42', text: '[0] button Save' };
      if (params.tool === 'computer_click') return { ok: true };
      throw new Error('unexpected native call');
    },
  });
  await repl.execute('capture', 'import {remember} from "retained-app"; remember(await cua.getApp("fixture.app"));');
  assert.equal(calls.length, 1);
  await repl.execute('same-generation', 'import {recall} from "retained-app"; await recall().click(0);');
  assert.equal(calls.length, 2);
  repl.reset();
  await assert.rejects(
    repl.execute('after-reset', 'import {recall} from "retained-app"; await recall().click(0);'),
    /reset|expired|invalid|active/,
  );
  assert.equal(calls.length, 2);
  await repl.execute('fresh', 'const freshApp = await cua.getApp("fixture.app"); await freshApp.click(0);');
  assert.deepEqual(calls.slice(2).map(call => call.id), ['fresh', 'fresh']);
});

test('in-process reset revokes retained output, direct RPC, process APIs and delayed dynamic imports', async t => {
  const root = await retainedModule(t);
  const calls = [];
  const output = [];
  const repl = new ReplKernel({
    cwd: root, send: value => output.push(value),
    rpc: async (method, params, id) => {
      calls.push({ method, params, id });
      return { stdout: 'managed', stderr: '', exitCode: 0 };
    },
  });
  await repl.execute('capture', `
    import {remember} from "retained-app";
    import {promisify} from "node:util";
    import {execFile} from "node:child_process";
    remember({
      write: nodeRepl.write, image: nodeRepl.emitImage, audio: nodeRepl.emitAudio, rpc: nodeRepl.rpc,
      execute: promisify(execFile), importLater: async () => import("node:child_process"),
      importStaticHelper: __cua_import__,
    });
  `);
  await repl.execute('same-generation', 'import {recall} from "retained-app"; await recall().execute("fixture-program", []);');
  assert.equal(calls.length, 1);
  repl.reset();
  await repl.execute('bind-retained', 'import {recall} from "retained-app"; const retained = recall();');
  for (const [name, code] of [
    ['text', 'retained.write("stale")'],
    ['image', 'retained.image({bytes:new Uint8Array([1])})'],
    ['audio', 'retained.audio({bytes:new Uint8Array([2])})'],
    ['rpc', 'await retained.rpc("computer.call", {})'],
    ['process', 'await retained.execute("fixture-program", [])'],
    ['dynamic-import', 'await retained.importLater()'],
    ['static-helper', 'await retained.importStaticHelper("node:child_process")'],
  ]) {
    await assert.rejects(repl.execute(`stale-${name}`, code), /expired after reset/);
  }
  assert.equal(calls.length, 1);
  assert.deepEqual(output, []);
  assert.equal(await repl.execute('fresh', 'import {promisify} from "node:util"; const {execFile} = await import("node:child_process"); (await promisify(execFile)("fixture-program", [])).stdout'), 'managed');
  assert.equal(calls.at(-1).id, 'fresh');
  await repl.execute('fresh-media', 'nodeRepl.emitAudio({bytes:new Uint8Array([3])});');
  assert.equal(output.at(-1).id, 'fresh-media');
});

test('module-directory registration validates real paths and remains usable across an in-process reset', async t => {
  const root = await retainedModule(t);
  const nodeModules = join(root, 'node_modules');
  const repl = new ReplKernel({ send() {}, rpc: async () => { throw new Error('unexpected RPC'); } });
  await assert.rejects(repl.addModuleDirectory('relative/node_modules'), /absolute/);
  await assert.rejects(repl.addModuleDirectory(join(nodeModules, 'retained-app', 'index.mjs')), /not a directory/);
  const result = await repl.addModuleDirectory(nodeModules);
  assert.equal(typeof result.path, 'string');
  assert.deepEqual(await repl.addModuleDirectory(nodeModules), result);
  await repl.execute('registered', 'import {remember} from "retained-app"; remember(37);');
  repl.reset();
  assert.equal(await repl.execute('registered-after-reset', 'import {recall} from "retained-app"; recall()'), 37);
});
