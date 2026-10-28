import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, writeFile, rm, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { ReplKernel } from '../src/kernel.mjs';

const kernel = (options = {}) => new ReplKernel({ send() {}, rpc: async () => { throw new Error('unexpected RPC'); }, ...options });

test('real VM persists redeclarable bindings, closures, destructuring, await and errors', async () => {
  const repl = kernel();
  await repl.execute('1', 'let value = await Promise.resolve(2); function read() { return value; }');
  assert.equal(await repl.execute('2', 'let value = 5; read()'), 5);
  assert.equal(await repl.execute('3', 'value += 2; value'), 7);
  await repl.execute('4', 'const {a: named, ...rest} = {a: 3, b: 4}; let [first, ...tail] = [1,2,3]');
  assert.equal(await repl.execute('5', 'named + rest.b + first + tail.length'), 10);
  await assert.rejects(repl.execute('6', 'let value = 20; throw new Error("cell failure")'), /cell failure/);
  assert.equal(await repl.execute('7', 'read()'), 20);
  await assert.rejects(repl.execute('8', 'let value=1; let value=2'), /already been declared/);
  assert.equal(await repl.execute('9', 'value'), 20);
  repl.reset();
  assert.equal(await repl.execute('10', 'typeof value'), 'undefined');
});

test('static and dynamic Node imports perform actual filesystem I/O and user package resolution', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'cua-repl-kernel-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(join(directory, 'user.mjs'), 'export const number = 17;');
  await mkdir(join(directory, 'node_modules', 'fixture-package'), { recursive: true });
  await writeFile(join(directory, 'node_modules', 'fixture-package', 'package.json'), JSON.stringify({ name: 'fixture-package', type: 'module', exports: './index.mjs' }));
  await writeFile(join(directory, 'node_modules', 'fixture-package', 'index.mjs'), 'export default 9;');
  const repl = kernel({ cwd: directory });
  await repl.execute('1', 'import {writeFile, readFile} from "node:fs/promises"; import {number} from "./user.mjs"; import pkg from "fixture-package"; await writeFile("' + join(directory, 'output.txt') + '", String(number + pkg))');
  assert.equal(await repl.execute('2', '(await readFile("' + join(directory, 'output.txt') + '")).toString()'), '26');
  assert.equal(await repl.execute('3', '(await import("./user.mjs")).number'), 17);
  await assert.rejects(repl.execute('4', 'await import("' + resolve('src/cli.mjs') + '")'), /trusted REPL/);
});

test('RPC is scoped to the active cell; late callbacks cannot reuse authority', async () => {
  const sent = [];
  const requests = [];
  const repl = kernel({ send: output => sent.push(output), rpc: async (method, params, id) => { requests.push({ method, params, id }); return { apps: [] }; } });
  await repl.execute('1', 'await cua.listApps(); let late; let done = new Promise(resolve => { setTimeout(() => { try { nodeRepl.write("stale"); } catch (e) { late = e.message; } resolve(); }, 20); });');
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(await repl.execute('2', 'late'), 'execution is no longer active');
  assert.deepEqual(requests, [{ method: 'computer.call', params: { tool: 'computer_list_apps', arguments: {} }, id: '1' }]);
  assert.equal(sent.filter(message => message.content?.text === 'stale').length, 0);
});

test('child_process uses the managed broker for imports and promisified execFile', async () => {
  const calls = [];
  const repl = kernel({ rpc: async (method, params) => { calls.push({ method, params }); return { stdout: 'managed\n', stderr: '', exitCode: 0 }; } });
  const result = await repl.execute('process', 'import {promisify} from "node:util"; const {execFile} = await import("node:child_process"); (await promisify(execFile)("/usr/bin/printf", ["managed"])).stdout');
  assert.equal(result, 'managed\n');
  assert.equal(calls[0].method, 'process.spawn');
  assert.equal(calls[0].params.executable, '/usr/bin/printf');
});
