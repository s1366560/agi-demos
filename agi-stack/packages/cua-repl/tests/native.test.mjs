import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFacade } from '../src/facade.mjs';

function fixture(reply, platform = 'darwin') {
  const calls = [];
  const output = [];
  const images = [];
  const cua = createFacade({
    enabledSurfaces: ['computer'],
    platform,
    write: value => output.push(value),
    emitImage: image => images.push(image),
    rpc: async (method, params) => {
      assert.equal(method, 'computer.call');
      calls.push(structuredClone(params));
      return reply(params.tool, params.arguments);
    },
  });
  return { cua, calls, output, images };
}

test('native inventory normalizes app metadata and lists only running app windows', async () => {
  const apps = [
    { id: 'editor', display_name: 'Editor', is_running: true },
    { id: 'viewer', displayName: 'Viewer', isRunning: true },
    { id: 'closed', display_name: 'Closed', is_running: false },
  ];
  const { cua, calls, output } = fixture((tool, args) => {
    if (tool === 'computer_list_apps') return JSON.stringify({ apps });
    assert.equal(tool, 'computer_list_windows');
    assert.notEqual(args.app, 'closed');
    return { windows: [{ id: args.app === 'editor' ? '41' : '42', title: 'Same title' }] };
  });
  const listed = await cua.listApps({ emit: false });
  assert.deepEqual(listed.map(app => [app.id, app.displayName, app.isRunning]), [
    ['editor', 'Editor', true], ['viewer', 'Viewer', true], ['closed', 'Closed', false],
  ]);
  assert.deepEqual(output, []);
  const windows = await cua.listWindows();
  assert.deepEqual(windows, [
    { id: '41', title: 'Same title', app: 'editor' },
    { id: '42', title: 'Same title', app: 'viewer' },
  ]);
  assert.deepEqual(output, [windows]);
  assert.deepEqual(calls.filter(call => call.tool === 'computer_list_windows')
    .map(call => call.arguments.app), ['editor', 'viewer']);
  assert.equal(apps[0].displayName, undefined, 'normalization must not mutate host inventory');
});

test('a unique window binds its app and every input uses the latest observed snapshot', async () => {
  let observations = 0;
  const { cua, calls, output } = fixture((tool, args) => {
    if (tool === 'computer_list_apps') return { apps: [
      { id: 'other', is_running: true }, { id: 'editor', is_running: true },
    ] };
    if (tool === 'computer_list_windows') return { windows: [
      { window_id: args.app === 'editor' ? '41' : '42', title: 'Same title' },
    ] };
    if (tool === 'computer_get_app_state') {
      observations += 1;
      return { state: `Editor state ${observations}`, snapshot_id: `snapshot-${observations}` };
    }
    return { ok: true };
  });
  const app = await cua.getApp({ windowId: 41 });
  assert.equal(Object.isFrozen(app), true);
  assert.deepEqual(calls.at(-1), {
    tool: 'computer_get_app_state',
    arguments: { app: 'editor', window_id: '41', disable_diff: true },
  });
  await app.click(0);
  assert.deepEqual(calls.at(-1).arguments, {
    app: 'editor', window_id: '41', snapshot_id: 'snapshot-1',
    element_index: 0, mouse_button: 'left', click_count: 1,
  });
  const emitted = output.length;
  assert.equal(await app.getAXState({ emit: false }), 'Editor state 2');
  assert.equal(output.length, emitted);
  await app.typeText('updated text', 2);
  assert.deepEqual(calls.at(-1), {
    tool: 'computer_type_text',
    arguments: { app: 'editor', window_id: '41', snapshot_id: 'snapshot-2', text: 'updated text', element_index: 2 },
  });
});

test('missing or ambiguous window references never observe or dispatch input to an app', async () => {
  for (const windowId of [99, 41]) {
    const { cua, calls } = fixture((tool) => {
      if (tool === 'computer_list_apps') return { apps: [
        { id: 'first', isRunning: true }, { id: 'second', isRunning: true },
      ] };
      assert.equal(tool, 'computer_list_windows', 'lookup must not dispatch to an unselected app');
      return { windows: [{ id: '41' }] };
    });
    await assert.rejects(cua.getApp({ windowId }), /window reference is missing or ambiguous/);
    assert.equal(calls.filter(call => call.tool === 'computer_list_windows').length, 2);
    assert.equal(calls.some(call => call.tool === 'computer_get_app_state'), false);
  }
  const { cua, calls } = fixture(() => assert.fail('invalid references must not reach RPC'));
  for (const reference of [null, '', {}, { windowId: '41' }, { windowId: 1.5 }]) {
    await assert.rejects(cua.getApp(reference), /app identifier or windowId/);
  }
  assert.deepEqual(calls, []);
});

test('an observation without a snapshot revokes input until a fresh snapshot is observed', async () => {
  let observations = 0;
  const { cua, calls } = fixture(tool => {
    if (tool !== 'computer_get_app_state') return { ok: true };
    observations += 1;
    return {
      text: `State ${observations}`, window_id: '41',
      ...(observations === 2 ? {} : { snapshot_id: `snapshot-${observations}` }),
    };
  });
  const app = await cua.getApp('editor');
  await app.click(0);
  await app.getAXState({ emit: false });
  const before = calls.length;
  await assert.rejects(app.click(0), /no current snapshot identity/);
  assert.equal(calls.length, before);
  await app.getAXState({ emit: false });
  await app.click(0);
  assert.equal(calls.at(-1).arguments.snapshot_id, 'snapshot-3');
});

test('invalid indices, coordinates and held durations fail before native input dispatch', async () => {
  const { cua, calls } = fixture(tool => tool === 'computer_get_app_state'
    ? { text: 'Editor', snapshot_id: 'current', window_id: '41' } : { ok: true });
  const app = await cua.getApp('editor');
  const before = calls.length;
  const invalid = [
    [() => app.click(-1), /non-negative safe integer/],
    [() => app.typeText('text', Number.MAX_SAFE_INTEGER + 1), /non-negative safe integer/],
    [() => app.click({ x: 4 }), /finite x and y/],
    [() => app.drag({ x: 0, y: 1 }, { x: Infinity, y: 2 }), /finite x and y/],
    [() => app.click(0, { durationMs: -1 }), /integer from 0 to 30000/],
    [() => app.pressKey('A', { durationMs: 30_001 }), /integer from 0 to 30000/],
  ];
  for (const [invoke, expected] of invalid) {
    await assert.rejects(async () => invoke(), expected);
    assert.equal(calls.length, before);
  }
  await app.click(0, { durationMs: 0 });
  assert.equal(calls.at(-1).arguments.duration_ms, 0);
  await app.pressKey('A', { durationMs: 30_000 });
  assert.equal(calls.at(-1).arguments.duration_ms, 30_000);
  await app.drag({ x: -10, y: 0 }, { x: 5.5, y: 10 });
  assert.deepEqual(calls.at(-1).arguments, {
    app: 'editor', snapshot_id: 'current', window_id: '41',
    from_x: -10, from_y: 0, to_x: 5.5, to_y: 10,
  });
});

test('platform input capabilities reject Windows holds and expose Linux character typing', async () => {
  for (const platform of ['win32', 'linux', 'darwin']) {
    const { cua, calls } = fixture(tool => tool === 'computer_get_app_state'
      ? { text: 'Editor', snapshot_id: 'current', window_id: '41' } : { ok: true }, platform);
    const app = await cua.getApp('editor');
    if (platform === 'win32') {
      const before = calls.length;
      await assert.rejects(async () => app.pressKey('A', { durationMs: 1 }), /unavailable on Windows/);
      assert.equal(calls.length, before);
      await app.pressKey('A');
      assert.equal(calls.at(-1).arguments.key, 'A');
      assert.equal('duration_ms' in calls.at(-1).arguments, false);
    }
    if (platform === 'linux') {
      await app.typeCharacters('characters');
      assert.deepEqual(calls.at(-1).arguments, {
        app: 'editor', snapshot_id: 'current', window_id: '41', text: 'characters', characters: true,
      });
    } else assert.equal(app.typeCharacters, undefined);
  }
});

test('authorized screenshot bytes stay separate from text and emit:false still refreshes binding', async () => {
  const bytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const dataBase64 = Buffer.from(bytes).toString('base64');
  let observations = 0;
  const { cua, calls, output, images } = fixture(tool => {
    if (tool !== 'computer_get_app_state') return { ok: true };
    observations += 1;
    return JSON.stringify({
      text: `State ${observations}`, snapshot_id: `snapshot-${observations}`,
      window_id: String(40 + observations),
      screenshot: { dataBase64, mime_type: 'image/png', path: '/private/screenshot.png' },
    });
  });
  const app = await cua.getApp('editor');
  assert.deepEqual(images, [], 'initial accessibility observation must not emit a screenshot');
  const before = output.length;
  assert.deepEqual(await app.getAXStateAndScreenshot({ emit: false }), { state: 'State 2', screenshot: bytes });
  assert.equal(output.length, before);
  assert.deepEqual(images, []);
  await app.click(0);
  assert.equal(calls.at(-1).arguments.snapshot_id, 'snapshot-2');
  assert.equal(calls.at(-1).arguments.window_id, '42');
  assert.deepEqual(await app.getScreenshot(), bytes);
  assert.deepEqual(images, [{ bytes, mimeType: 'image/png' }]);
  assert.equal(output.at(-1), 'State 3');
  assert.equal(output.some(value => String(value).includes(dataBase64)), false);
  assert.equal(output.some(value => String(value).includes('/private/screenshot.png')), false);
});

test('screenshot paths or artifact receipts cannot substitute for authorized image bytes', async () => {
  const { cua, output, images } = fixture(() => ({
    text: 'Editor', snapshot_id: 'current', window_id: '41',
    screenshot: { path: '/private/unreadable.png', artifact_id: 'private-artifact', mimeType: 'image/png' },
  }));
  const app = await cua.getApp('editor');
  const before = output.length;
  await assert.rejects(app.getScreenshot(), /host did not provide authorized screenshot bytes/);
  assert.equal(output.length, before);
  assert.deepEqual(images, []);
});

test('audio stop rejects discard before RPC and preserves recording scope while stripping save:true', async () => {
  const recording = { recording_id: 'owned-recording' };
  const receipt = { recording_id: recording.recording_id, status: 'saved', media: [{ artifact_id: 'saved-audio' }] };
  const { cua, calls, output, images } = fixture(tool => {
    if (tool === 'computer_audio_start') return recording;
    if (tool === 'computer_audio_status') return { recordings: [recording] };
    assert.equal(tool, 'computer_audio_stop');
    return JSON.stringify(receipt);
  });
  assert.deepEqual(await cua.computer.audio.start({ source: 'mixed' }), recording);
  assert.deepEqual(calls.at(-1), {
    tool: 'computer_audio_start', arguments: { max_duration_ms: 60_000, source: 'mixed' },
  });
  await cua.computer.audio.status({ recording_id: recording.recording_id });
  assert.deepEqual(calls.at(-1).arguments, recording);
  const before = calls.length;
  for (const options of [null, [], false, { save: false }, { save: 'true' }]) {
    assert.throws(() => cua.computer.audio.stop(options), /options must be an object|always saves the recording/);
    assert.equal(calls.length, before);
  }
  const scoped = { recording_id: recording.recording_id, save: true };
  assert.deepEqual(await cua.computer.audio.stop(scoped), receipt);
  assert.deepEqual(calls.at(-1), { tool: 'computer_audio_stop', arguments: recording });
  assert.equal(scoped.save, true, 'compatibility translation must not mutate caller options');
  await cua.computer.audio.stop();
  assert.deepEqual(calls.at(-1), { tool: 'computer_audio_stop', arguments: {} });
  assert.deepEqual(output, [], 'recording receipts must not be emitted implicitly');
  assert.deepEqual(images, []);
});
