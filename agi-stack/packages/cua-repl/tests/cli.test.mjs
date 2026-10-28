import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

test('real child process speaks JSONL, returns media and round-trips host RPC', async t => {
  const child = spawn(process.execPath, ['--experimental-vm-modules', fileURLToPath(new URL('../src/cli.mjs', import.meta.url))], { stdio: ['pipe', 'pipe', 'pipe'] });
  t.after(() => child.kill());
  const frames = [];
  let wake;
  createInterface({ input: child.stdout }).on('line', line => {
    const frame = JSON.parse(line); frames.push(frame); wake?.();
    if (frame.type === 'rpc') child.stdin.write(JSON.stringify({ type: 'rpc_response', id: frame.id, result: { apps: [{ id: 'fixture', display_name: 'Fixture', is_running: true }] } }) + '\n');
  });
  const wait = async predicate => {
    for (;;) {
      const found = frames.find(predicate); if (found) return found;
      await new Promise((resolve, reject) => { const timer = setTimeout(() => reject(new Error('protocol timed out')), 3000); wake = () => { clearTimeout(timer); resolve(); }; });
    }
  };
  await wait(frame => frame.type === 'ready');
  child.stdin.write(JSON.stringify({ type: 'execute', id: 'one', code: 'let apps = await cua.listApps({emit:false}); nodeRepl.emitImage({data:"AA==",mimeType:"image/png"}); apps[0].displayName' }) + '\n');
  assert.equal((await wait(frame => frame.type === 'result' && frame.id === 'one')).value, 'Fixture');
  assert.equal(frames.find(frame => frame.type === 'output').content.type, 'image');
  child.stdin.write(JSON.stringify({ type: 'execute', id: 'two', code: 'apps.length' }) + '\n');
  assert.equal((await wait(frame => frame.type === 'result' && frame.id === 'two')).value, 1);
  child.stdin.write(JSON.stringify({ type: 'reset', id: 'reset' }) + '\n');
  assert.equal((await wait(frame => frame.id === 'reset')).ok, true);
  child.stdin.write(JSON.stringify({ type: 'execute', id: 'three', code: 'typeof apps' }) + '\n');
  assert.equal((await wait(frame => frame.type === 'result' && frame.id === 'three')).value, 'undefined');
});
