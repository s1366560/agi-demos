import assert from 'node:assert/strict';
import { test } from 'node:test';
import { once } from 'node:events';
import { promisify } from 'node:util';
import { managedProcesses } from '../src/processes.mjs';

test('managed process I/O and exit failures retain broker results without escaping cancellation ownership', async () => {
  const calls = [];
  const api = managedProcesses(async (method, params) => {
    calls.push({ method, params });
    return { stdout: 'partial output', stderr: 'command failed', exitCode: 3 };
  });
  const child = api.spawn('/authorized/program', ['arg'], { cwd: '/workspace', env: { FIXTURE: 'value' }, timeout: 1_000 });
  child.stdin.write('input');
  assert.equal(child.ref(), child);
  assert.equal(child.unref(), child);
  assert.throws(() => child.kill(), /cancel the active execution/);
  const [code] = await once(child, 'close');
  assert.equal(code, 3);
  assert.equal(child.exitCode, 3);
  assert.deepEqual(calls[0].params, { executable: '/authorized/program', args: ['arg'], cwd: '/workspace', env: { FIXTURE: 'value' }, timeoutMs: 1_000, input: 'input' });
  await assert.rejects(promisify(api.execFile)('/authorized/program', []), error => error.code === 3 && error.stdout === 'partial output' && error.stderr === 'command failed');
  for (const name of ['spawnSync', 'execSync', 'execFileSync']) assert.throws(() => api[name]('/authorized/program'), /synchronous/);
  assert.throws(() => api.spawn('/authorized/program', [], { detached: true }), /detached/);
  assert.throws(() => api.spawn('/authorized/program', [1]), /string arguments/);
});

test('broker transport failure reaches callbacks once and shell commands stay explicit broker operations', async () => {
  const failure = new Error('broker denied');
  const api = managedProcesses(async () => { throw failure; });
  let callbacks = 0;
  await new Promise(resolve => api.execFile('/authorized/program', error => { callbacks++; assert.equal(error, failure); resolve(); }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(callbacks, 1);
  const calls = [];
  const allowed = managedProcesses(async (_method, params) => { calls.push(params); return { stdout: 'done', exitCode: 0 }; });
  assert.deepEqual(await promisify(allowed.exec)('printf done'), { stdout: 'done', stderr: '' });
  assert.deepEqual(calls[0], { executable: '/bin/sh', args: ['-c', 'printf done'] });
  const child = allowed.fork('/owned/script.mjs', [], { execPath: '/authorized/node' });
  await once(child, 'close');
  assert.deepEqual(calls.at(-1), { executable: '/authorized/node', args: ['/owned/script.mjs'] });
});
