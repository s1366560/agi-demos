import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { resultPreview } from '../src/result-preview.mjs';

test('JSONL previews large final media while later cells retain complete byte arrays and data URLs', async t => {
  const child = spawn(process.execPath, ['--experimental-vm-modules', fileURLToPath(new URL('../src/cli.mjs', import.meta.url))], { stdio: ['pipe', 'pipe', 'pipe'] });
  t.after(() => child.kill());
  const pending = new Map();
  let ready;
  const started = new Promise(resolve => { ready = resolve; });
  createInterface({ input: child.stdout }).on('line', line => {
    assert.ok(Buffer.byteLength(line) < 300_000, 'preview must remain below the control frame limit');
    const frame = JSON.parse(line);
    if (frame.type === 'ready') ready();
    else pending.get(frame.id)?.(frame);
  });
  const execute = async (id, code) => {
    await started;
    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('JSONL result timed out')), 5_000);
      pending.set(id, frame => { clearTimeout(timer); pending.delete(id); resolve(frame); });
    });
    child.stdin.write(`${JSON.stringify({ type: 'execute', id, code })}\n`);
    return response;
  };
  const large = await execute('large', 'var retainedAudio = {filepath:"/owned.wav",bytes:new Uint8Array(28_800_000),data_url:"data:audio/wav;base64,"+"A".repeat(38_400_000)}; retainedAudio;');
  assert.equal(large.ok, true);
  assert.equal(large.value.filepath, '/owned.wav');
  assert.equal(large.value.bytes.byteLength, 28_800_000);
  assert.equal(large.value.bytes.truncated, true);
  assert.equal(large.value.data_url.truncated, true);
  const retained = await execute('retained', '[retainedAudio.bytes.byteLength,retainedAudio.data_url.length]');
  assert.deepEqual(retained.value, [28_800_000, 38_400_022]);
});

test('result previews bound nested collections and cycles while preserving ordinary scalar and Date results', () => {
  const cyclic = { value: 1 }; cyclic.self = cyclic;
  assert.deepEqual(resultPreview(cyclic), { value: 1, self: '[Circular]' });
  assert.equal(resultPreview(new Date('2026-10-29T00:00:00Z')), '2026-10-29T00:00:00.000Z');
  assert.equal(resultPreview(10n), '10n');
  assert.deepEqual(resultPreview({ answer: true, value: null }), { answer: true, value: null });
  assert.equal(resultPreview(Array.from({ length: 150 }, (_, index) => index)).at(-1).omittedItems, 50);
  assert.ok(JSON.stringify(resultPreview(Array.from({ length: 200 }, () => 'x'.repeat(200_000)))).length < 300_000);
});
