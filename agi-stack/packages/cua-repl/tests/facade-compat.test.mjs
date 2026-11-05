import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';
import { ReplKernel } from '../src/kernel.mjs';
import { readFile, rm } from 'node:fs/promises';
import { dirname } from 'node:path';

function nativeFixture() {
  const calls = [];
  let snapshot = 'first';
  const cua = createFacade({ enabledSurfaces: ['computer'], platform: 'darwin', write() {}, emitImage() {},
    rpc: async (_method, params) => {
      calls.push(params);
      if (params.tool === 'computer_resolve_app') return { status: 'running', app: params.arguments.app, process_id: 42, identity_digest: 'a'.repeat(64) };
      if (params.tool === 'computer_list_apps') return { apps: [{ id: 'editor', is_running: true }] };
      if (params.tool === 'computer_get_app_state') return { app: 'editor', text: '[0] text field', snapshot_id: snapshot, window_id: '42' };
      if (params.tool === 'computer_audio_start') return { recording_id: 'owned' };
      if (params.tool === 'computer_audio_stop') return { media: [{ inline: true, data: 'UklGRg==', mimeType: 'audio/wav', path: '/owned/recording.wav' }] };
      return { ok: true };
    } });
  return { cua, calls, setSnapshot: value => { snapshot = value; } };
}

test('initialize is the inventory alias and raw native methods retain observed snapshot authority', async () => {
  const { cua, calls, setSnapshot } = nativeFixture();
  assert.equal(cua.initialize, cua.getState);
  assert.deepEqual((await cua.initialize({ emit: false })).apps.map(app => app.id), ['editor']);
  assert.equal(cua.computer.target, 'mac');
  assert.deepEqual((await cua.computer.list_apps()).map(app => app.id), ['editor']);
  assert.equal((await cua.computer.list_apps())[0].isRunning, true);
  await assert.rejects(cua.computer.click({ app: 'editor', element_index: 0 }), /observe|snapshot/);
  const observed = await cua.computer.get_app_state({ app: 'editor', disableDiff: true });
  assert.equal(observed.app, 'editor');
  assert.equal(observed.text, '[0] text field');
  assert.equal(observed.screenshot, null);
  await cua.computer.click({ app: 'editor', element_index: 0, duration: 0.25 });
  assert.deepEqual(calls.at(-1).arguments, { app: 'editor', snapshot_id: 'first', window_id: '42', element_index: 0, mouse_button: 'left', click_count: 1, duration_ms: 250 });
  setSnapshot('second');
  const app = await cua.getApp('editor');
  await cua.computer.type_text({ app: 'editor', text: 'shared observation' });
  assert.equal(calls.at(-1).arguments.snapshot_id, 'second');
  await app.click([10, 20]);
  assert.equal(calls.at(-1).arguments.x, 10);
  assert.equal(calls.at(-1).arguments.y, 20);
  setSnapshot(undefined);
  await cua.computer.get_app_state({ app: 'editor' });
  const before = calls.length;
  await assert.rejects(cua.computer.press_key({ app: 'editor', key: 'Return' }), /snapshot/);
  assert.equal(calls.length, before);
});

test('raw native actions validate before dispatch and translate the complete macOS input surface', async () => {
  const { cua, calls } = nativeFixture();
  await cua.computer.get_app_state({ app: 'editor' });
  for (const [name, input, expected] of [
    ['drag', { from_x: 1, from_y: 2, to_x: 3, to_y: 4 }, 'computer_drag'],
    ['paste', { text: '<b>hello</b>', format: 'html' }, 'computer_paste'],
    ['perform_secondary_action', { element_index: 0, action: 'AXPress' }, 'computer_secondary_action'],
    ['press_key', { key: 'Return', duration: 1 }, 'computer_press_key'],
    ['scroll', { element_index: 0, direction: 'down', pages: 2 }, 'computer_scroll'],
    ['select_text', { element_index: 0, text: 'hello', selection_type: 'cursor_after' }, 'computer_select_text'],
    ['set_value', { element_index: 0, value: 'hello' }, 'computer_set_value'],
    ['type_text', { text: 'hello' }, 'computer_type_text'],
  ]) {
    assert.equal(await cua.computer[name]({ app: 'editor', ...input }), undefined);
    assert.equal(calls.at(-1).tool, expected);
    assert.equal(calls.at(-1).arguments.snapshot_id, 'first');
    assert.equal(calls.at(-1).arguments.window_id, '42');
    if (name === 'select_text') assert.equal(calls.at(-1).arguments.cursor, 'after');
  }
  const before = calls.length;
  for (const input of [{ app: 'editor', element_index: -1 }, { app: 'editor', x: 1 }, { app: 'editor', element_index: 0, duration: 31 }, { app: 'editor', element_index: 0, unknown: true }]) {
    await assert.rejects(cua.computer.click(input), /index|point|duration|unknown/);
  }
  assert.equal(calls.length, before);
});

test('raw native observations return authorized data URLs and launch keeps exact app identity and host denial', async () => {
  const calls = [];
  const cua = createFacade({ enabledSurfaces: ['computer'], platform: 'darwin', write() {}, emitImage() {}, rpc: async (_method, params) => {
    calls.push(params);
    if (params.tool === 'computer_get_app_state') return { app: 'editor', text: 'State', snapshot_id: 'private-snapshot', screenshot: { url: 'data:image/jpeg;base64,/9j/', path: '/private/host.png' } };
    if (params.arguments.app === 'forbidden') return { error: { code: 'permission_denied', message: 'Host denied launch' } };
    return { ok: true };
  } });
  assert.deepEqual(await cua.computer.get_app_state({ app: 'editor' }), { app: 'editor', text: 'State', screenshot: { url: 'data:image/jpeg;base64,/9j/' } });
  assert.equal(await cua.computer.launch_app({ app: 'com.example.editor' }), undefined);
  assert.deepEqual(calls.at(-1), { tool: 'computer_launch_app', arguments: { app: 'com.example.editor' } });
  await assert.rejects(cua.computer.launch_app({ app: 'forbidden' }), error => error.code === 'permission_denied');
  const before = calls.length;
  await assert.rejects(cua.computer.launch_app({ app: 'editor', command: '/bin/sh' }), /unknown/);
  assert.equal(calls.length, before);
});

test('macOS getApp resolves installed identity and launches only a structured stopped target before observation', async () => {
  for (const denied of [false, true]) {
    const calls = [];
    const cua = createFacade({ enabledSurfaces: ['computer'], platform: 'darwin', write() {}, emitImage() {}, rpc: async (_method, params) => {
      calls.push(params);
      if (params.tool === 'computer_resolve_app') return { status: 'not_running', app: 'com.example.editor', identity_digest: 'a'.repeat(64), process_id: 0 };
      if (params.tool === 'computer_launch_app') {
        assert.equal(params.arguments.app, 'com.example.editor');
        if (denied) throw Object.assign(new Error('Launch denied'), { code: 'permission_denied' });
        return { process_id: 42 };
      }
      assert.equal(params.tool, 'computer_get_app_state');
      return { text: 'Editor ready', snapshot_id: 'current', window_id: '42' };
    } });
    if (denied) await assert.rejects(cua.getApp('Editor'), /Launch denied/);
    else assert.equal(await (await cua.getApp('Editor')).getAXState({ emit: false }), 'Editor ready');
    assert.deepEqual(calls.slice(0, 2).map(call => call.tool), ['computer_resolve_app', 'computer_launch_app']);
    assert.equal(calls.some(call => call.tool === 'computer_get_app_state'), !denied);
  }
  const cua = createFacade({ enabledSurfaces: ['computer'], platform: 'darwin', write() {}, emitImage() {}, rpc: async () => ({ ok: true }) });
  await assert.rejects(cua.getApp('Editor'), /identity|target/);
});

test('legacy system audio uses bounded durations and returns byte and data URL compatible media', async t => {
  const { cua, calls } = nativeFixture();
  assert.equal(await cua.computer.start_audio_recording(), undefined);
  assert.deepEqual(calls.at(-1), { tool: 'computer_audio_start', arguments: { source: 'system', max_duration_ms: 60_000 } });
  const audio = await cua.computer.stop_audio_recording();
  t.after(() => rm(dirname(audio.filepath), { recursive: true, force: true }));
  assert.notEqual(audio.filepath, '/owned/recording.wav');
  assert.deepEqual(audio.bytes, Uint8Array.from(Buffer.from('UklGRg==', 'base64')));
  assert.equal(audio.data_url, 'data:audio/wav;base64,UklGRg==');
  assert.deepEqual(await readFile(audio.filepath), Buffer.from('UklGRg==', 'base64'));
  assert.deepEqual(calls.at(-1).arguments, { recording_id: 'owned' });
  const before = calls.length;
  for (const max_duration_ms of [99, 300001, 1.5, NaN]) await assert.rejects(cua.computer.start_audio_recording({ max_duration_ms }), /100.*300000/);
  assert.equal(calls.length, before);
});

test('nodeRepl preserves stable output identities, readonly turn context and audio byte containers', async () => {
  const output = [];
  const repl = new ReplKernel({ send: value => output.push(value), rpc() { throw new Error('unexpected RPC'); } });
  await repl.execute('one', 'nodeRepl.write("first", "cua.state"); nodeRepl.emitAudio("data:audio/wav;base64,UklGRg=="); nodeRepl.emitAudio({data_url:"data:audio/wav;base64,UklGRg=="});', { requestMeta: { turn: 'one', nested: { immutable: true } } });
  assert.deepEqual(output[0].content, { type: 'text', text: 'first', itemId: 'cua.state' });
  assert.deepEqual(output.slice(1).map(value => value.content), Array(2).fill({ type: 'audio', mimeType: 'audio/wav', data: 'UklGRg==' }));
  assert.equal(await repl.execute('two', 'nodeRepl.requestMeta.turn', { requestMeta: { turn: 'two' } }), 'two');
  assert.equal(await repl.execute('readonly', 'nodeRepl.requestMeta.turn = "changed"; nodeRepl.requestMeta.turn;', { requestMeta: { turn: 'original' } }), 'original');
  await assert.rejects(repl.execute('bad-url', 'nodeRepl.emitAudio("data:text/plain;base64,AA==");'), /audio/);
});

test('documentation identities stay stable and rewrite emits once per active context', async () => {
  const output = [];
  const repl = new ReplKernel({ enabledSurfaces: ['computer'], send: value => output.push(value), rpc: async () => ({ apps: [] }) });
  await repl.execute('one', 'await cua.getState({emit:false}); await cua.rewriteDocumentation();', { requestMeta: { turn: 'one', nested: { readonly: true } } });
  assert.deepEqual(output.map(value => value.content.itemId), ['cua.core']);
  await repl.execute('two', 'await cua.rewriteDocumentation(); await cua.rewriteDocumentation();', { requestMeta: { turn: 'two' } });
  assert.deepEqual(output.map(value => [value.id, value.content.itemId]), [['one', 'cua.core'], ['two', 'cua.core']]);
  assert.equal(await repl.execute('immutable', 'nodeRepl.requestMeta.nested.readonly=false; nodeRepl.requestMeta.nested.readonly', { requestMeta: { nested: { readonly: true } } }), true);
});
