import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { nativeAudio } from '../src/audio.mjs';
import { ReplKernel } from '../src/kernel.mjs';

async function fixture(t, change = value => value, size = 20) {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), 'cua-audio-contract-'));
  t.after(() => rm(temporaryDirectory, { recursive: true, force: true }));
  const content = Buffer.alloc(size, 7);
  const calls = [];
  const call = async (tool, args) => {
    calls.push({ tool, args });
    if (tool === 'computer_audio_start') return { recording_id: 'owned-recording' };
    if (tool === 'computer_audio_stop') return { recordings: [{ recording_id: 'owned-recording', artifacts: [{ artifact_id: 'owned-wav' }] }] };
    assert.equal(tool, 'computer_audio_read');
    assert.equal(args.recording_id, 'owned-recording');
    const bytes = content.subarray(args.offset, args.offset + 128 * 1024);
    return change({ artifact_id: 'owned-wav', recording_id: 'owned-recording', mime_type: 'audio/wav',
      offset: args.offset, next_offset: args.offset + bytes.length, size_bytes: content.length,
      eof: args.offset + bytes.length === content.length, data_base64: bytes.toString('base64') });
  };
  return { audio: nativeAudio({ call, temporaryDirectory }), call, calls, content, temporaryDirectory };
}

test('maximum-duration legacy recording reads owned bounded chunks and writes a private WAV', async t => {
  const { audio, calls, content, temporaryDirectory } = await fixture(t, value => value, 24_000 * 2 * 2 * 300);
  await audio.start_audio_recording({ max_duration_ms: 300_000 });
  const result = await audio.stop_audio_recording();
  assert.equal(result.bytes.byteLength, content.length);
  assert.deepEqual(Buffer.from(result.bytes), content);
  assert.deepEqual(await readFile(result.filepath), content);
  assert.equal((await stat(result.filepath)).mode & 0o777, 0o600);
  assert.ok(result.filepath.startsWith(`${temporaryDirectory}/`));
  assert.ok(calls.filter(call => call.tool === 'computer_audio_read').length > 1);
  assert.ok(calls.filter(call => call.tool === 'computer_audio_read').every(call => call.args.artifact_id === 'owned-wav'));
});

test('audio chunks fail closed on owner, size, offset, encoding and completion mismatches', async t => {
  for (const patch of [
    { recording_id: 'another-recording' }, { artifact_id: 'another-artifact' }, { offset: 1 },
    { next_offset: 5 }, { mime_type: 'text/plain' }, { data_base64: 'not base64' },
    { size_bytes: 21, eof: true }, { size_bytes: 0 }, { eof: false },
  ]) {
    await t.test(JSON.stringify(patch), async t => {
      const { audio } = await fixture(t, value => ({ ...value, ...patch }));
      await audio.start_audio_recording();
      await assert.rejects(audio.stop_audio_recording(), /artifact|audio/);
    });
  }
});

test('audio artifact reads require a recording identity and never resolve arbitrary file paths', async t => {
  const { audio, calls } = await fixture(t);
  await assert.rejects(audio.readArtifact({ filepath: '/private/unrelated.wav' }), /recording_id/);
  assert.equal(calls.length, 0);
  await assert.rejects(audio.stop_audio_recording(), /no legacy/);
  await assert.rejects(audio.start_audio_recording({ source: 'microphone' }), /unknown/);
});

test('audio emission accepts byte containers and rejects malformed or mismatched data URLs before output', async () => {
  const output = [];
  const repl = new ReplKernel({ send: value => output.push(value), rpc() { throw new Error('unexpected RPC'); } });
  await repl.execute('bytes', 'nodeRepl.emitAudio(new Uint8Array([1,2,3])); nodeRepl.emitAudio(new Uint8Array([1,2,3]).buffer);');
  assert.deepEqual(output.map(value => value.content.data), ['AQID', 'AQID']);
  for (const code of [
    'nodeRepl.emitAudio("data:audio/wav,raw")', 'nodeRepl.emitAudio("data:audio/wav;base64,not base64")',
    'nodeRepl.emitAudio({data:"AQID",mimeType:"text/plain"})',
  ]) await assert.rejects(repl.execute('invalid', code), /audio/);
  assert.equal(output.length, 2);
});

test('large audio uses an unforgeable owned temporary filename and keeps the control frame small', async t => {
  const { call, content, temporaryDirectory } = await fixture(t, value => value, 11 * 1024 * 1024);
  const output = [];
  const repl = new ReplKernel({ temporaryDirectory, enabledSurfaces: ['computer'], send: value => output.push(value),
    rpc: async (method, params) => { assert.equal(method, 'computer.call'); return call(params.tool, params.arguments); } });
  await repl.execute('record', 'await cua.computer.start_audio_recording(); var audio = await cua.computer.stop_audio_recording(); nodeRepl.emitAudio(audio);');
  const media = output.find(value => value.content.type === 'audio').content;
  assert.deepEqual(Object.keys(media).sort(), ['filename', 'mimeType', 'type']);
  assert.match(media.filename, /^[a-f0-9-]+\.wav$/);
  assert.deepEqual(await readFile(join(temporaryDirectory, media.filename)), content);
  assert.ok(JSON.stringify(media).length < 200);
  assert.equal(await repl.execute('shape', 'Object.keys(audio).sort().join(",")'), 'bytes,data_url,filepath');
  await assert.rejects(repl.execute('forged', 'nodeRepl.emitAudio({...audio, filename:"guessed.wav"});'), /inline limit/);
  assert.equal(output.filter(value => value.content.type === 'audio').length, 1);
});
