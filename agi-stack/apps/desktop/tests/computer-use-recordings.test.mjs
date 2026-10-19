import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const root = '/tmp/agistack-desktop-test-dist';
const { computerUseTimestamp } = require(`${root}/src/api/computerUseTime.js`);
const { computerUseRecordingDuration, computerUseRecordingEndReasonKey } = require(
  `${root}/src/api/computerUseRecording.js`,
);
const { isComputerUseSnapshotForScope } = require(`${root}/src/api/computerUseContractV2.js`);
const recording = {
  recording_id: 'recording-1',
  session_id: 'native-session-1',
  conversation_id: 'conversation-1',
  run_id: 'run-1',
  source: 'mixed',
  status: 'recording',
  started_at: '2026-10-19T01:00:00Z',
  elapsed_ms: 5000,
  artifacts: [],
};
const snapshot = {
  plugin_id: 'memstack-computer-use',
  device_id: 'device-1',
  helper_available: true,
  scope: { tenant_id: 'tenant-1', project_id: 'project-1' },
  instance: { installed: true, enabled: true, revision: 1 },
  sessions: [],
  grants: [],
  pending: [],
};
test('preview timestamps support native Unix seconds, RFC3339 and invalid values without inventing time', () => {
  assert.equal(computerUseTimestamp(1792371600.125), '2026-10-19T01:00:00.125Z');
  assert.equal(computerUseTimestamp('2026-10-19T09:00:00+08:00'), '2026-10-19T09:00:00+08:00');
  assert.equal(computerUseTimestamp('2024-02-29T12:00:00Z'), '2024-02-29T12:00:00Z');
  for (const value of [
    null,
    undefined,
    NaN,
    Infinity,
    1e30,
    '',
    '2026',
    'invalid',
    '2026-02-30T12:00:00Z',
    '2026-02-29T12:00:00Z',
    '2026-10-19T24:00:00Z',
  ])
    assert.equal(computerUseTimestamp(value), null);
  const { computerUseResultPresentationV2 } = require(
    `${root}/src/features/chat/computerUseResultPresentationV2.js`,
  );
  assert.equal(
    computerUseResultPresentationV2({ observed_at: 1792371600.125 }).observedAt,
    '2026-10-19T01:00:00.125Z',
  );
});
test('actual native numeric timestamps render in preview and invalid timestamps display localized unknown time', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const { ComputerUseTargetPreview } = require(
    `${root}/src/features/settings/ComputerUseTargetPreview.js`,
  );
  const render = (observed_at) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ComputerUseTargetPreview, {
          client: null,
          presentation: {
            phase: 'paused',
            preview: {
              artifact_id: 'cua-image-abcd',
              mime_type: 'image/png',
              observed_at,
            },
          },
        }),
      ),
    );
  assert.match(render(1792371600.125), /dateTime="2026-10-19T01:00:00.125Z"/u);
  assert.doesNotMatch(render(1792371600.125), /Observation time unknown/u);
  for (const value of [undefined, 'invalid', '2026-02-30T12:00:00Z']) {
    assert.doesNotMatch(render(value), /<time/u);
    assert.match(render(value), /Observation time unknown/u);
  }
  const previousWindow = globalThis.window;
  try {
    globalThis.window = { localStorage: { getItem: () => 'zh-CN' } };
    assert.match(render('2026-02-30T12:00:00Z'), /观察时间未知/u);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
test('recording durations advance only while recording and preserve completed duration', () => {
  const now = Date.parse(recording.started_at) + 65000;
  assert.equal(computerUseRecordingDuration(recording, now), '1:05');
  assert.equal(
    computerUseRecordingDuration(
      { ...recording, status: 'saved', elapsed_ms: 62000 },
      now + 600000,
    ),
    '1:02',
  );
  assert.equal(
    computerUseRecordingDuration({ ...recording, started_at: 'invalid', elapsed_ms: 5000 }, now),
    '0:05',
  );
});
test('structured native end reasons have localized keys and unknown protocol reasons use a neutral fallback', () => {
  for (const reason of [
    'user_stopped',
    'user_paused',
    'model_stopped',
    'session_ended',
    'session_reset',
    'revoked',
    'disabled',
    'lease_expired',
    'cancelled',
    'duration_limit',
    'byte_limit',
    'start_failed',
    'capture_error',
    'device_lost',
    'capture_ended',
    'process_ended',
  ]) {
    assert.equal(computerUseRecordingEndReasonKey(reason), `cua.recording.ended.${reason}`);
  }
  assert.equal(
    computerUseRecordingEndReasonKey('unknown future reason'),
    'cua.recording.ended.unknown',
  );
});
test('legacy snapshots remain valid and malformed recording receipts fail closed', () => {
  const scope = { tenantId: 'tenant-1', projectId: 'project-1' };
  assert.equal(isComputerUseSnapshotForScope(snapshot, scope), true);
  assert.equal(
    isComputerUseSnapshotForScope({ ...snapshot, recordings: [recording] }, scope),
    true,
  );
  assert.equal(
    isComputerUseSnapshotForScope(
      {
        ...snapshot,
        recordings: [
          {
            ...recording,
            elapsed_ms: null,
            ended_at: null,
            error_code: null,
            end_reason: null,
          },
        ],
      },
      scope,
    ),
    true,
  );
  for (const invalid of [
    null,
    { ...recording, status: 'unknown' },
    { ...recording, source: 'camera' },
    { ...recording, recording_id: '' },
    { ...recording, elapsed_ms: -1 },
    { ...recording, can_retry_export: 'yes' },
    { ...recording, error_code: {} },
    {
      ...recording,
      artifacts: [
        {
          kind: 'audio',
          artifact_id: 'file:///private/audio.wav',
          mime_type: 'audio/wav',
        },
      ],
    },
  ])
    assert.equal(
      isComputerUseSnapshotForScope({ ...snapshot, recordings: [invalid] }, scope),
      false,
    );
});
test('recording controls stop the exact recording and expose saving, retry and playback without a start action', async () => {
  const React = require('react');
  const jsx = require('react/jsx-runtime');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const { ComputerUseRecordings } = require(
    `${root}/src/features/settings/ComputerUseRecordings.js`,
  );
  const buttons = [],
    operations = [];
  const originalJsx = jsx.jsx,
    originalJsxs = jsx.jsxs;
  const intercept =
    (delegate) =>
    (type, props, ...rest) => {
      if (type === 'button') buttons.push(props);
      return delegate(type, props, ...rest);
    };
  try {
    jsx.jsx = intercept(originalJsx);
    jsx.jsxs = intercept(originalJsxs);
    const render = (value, stopping = false) =>
      renderToStaticMarkup(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(ComputerUseRecordings, {
            recordings: [value],
            stopping,
            client: {
              audio: async () => {
                throw new Error('playback must be user initiated');
              },
            },
            manage: async (operation) => {
              operations.push(operation);
            },
          }),
        ),
      );
    assert.match(render(recording), /Microphone and system audio/u);
    await buttons.find((button) => button.children === 'Stop recording').onClick();
    assert.deepEqual(operations, [
      {
        action: 'audio_stop',
        session_id: 'native-session-1',
        recording_id: 'recording-1',
      },
    ]);
    buttons.length = 0;
    render(recording, true);
    assert.equal(buttons.find((button) => button.children === 'Stop recording').disabled, true);
    buttons.length = 0;
    assert.match(render({ ...recording, status: 'pending_export' }), /Saving recording/u);
    assert.equal(buttons.length, 0);
    buttons.length = 0;
    const failed = render({
      ...recording,
      status: 'failed',
      error_code: 'audio_export_failed',
      can_retry_export: true,
    });
    assert.match(failed, /The recording could not be saved/u);
    assert.match(
      failed,
      /<details><summary>Technical details<\/summary><code>audio_export_failed<\/code><\/details>/u,
    );
    await buttons.find((button) => button.children === 'Retry saving recording').onClick();
    assert.deepEqual(operations[1], operations[0]);
    buttons.length = 0;
    const saved = render({
      ...recording,
      status: 'saved',
      error_code: 'audio_partial',
      end_reason: 'device_lost',
      partial: true,
      can_retry_export: false,
      artifacts: [
        {
          kind: 'audio',
          artifact_id: 'cua-audio-abcd',
          mime_type: 'audio/wav',
        },
      ],
    });
    assert.match(saved, /Recording saved/u);
    assert.match(saved, /Audio capture device disconnected/u);
    assert.match(saved, /Only part of the recording was captured/u);
    assert.match(saved, /Audio capture did not finish successfully/u);
    assert.match(saved, /Preview recording/u);
    assert.doesNotMatch(saved, /Retry saving|Stop recording|Start recording|data:|file:/u);
  } finally {
    jsx.jsx = originalJsx;
    jsx.jsxs = originalJsxs;
  }
});
test('missing recording sources display the localized save failure without retry or capture-failure claims', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const { ComputerUseRecordings } = require(
    `${root}/src/features/settings/ComputerUseRecordings.js`,
  );
  const render = () =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ComputerUseRecordings, {
          recordings: [
            {
              ...recording,
              status: 'failed',
              error_code: 'cua_audio_source_missing',
              end_reason: 'user_paused',
              can_retry_export: false,
            },
          ],
          stopping: false,
          client: null,
          manage: async () => {},
        }),
      ),
    );
  const previousWindow = globalThis.window;
  try {
    globalThis.window = { localStorage: { getItem: () => 'en' } };
    const english = render();
    assert.match(english, /The recording source file no longer exists and cannot be saved\./u);
    assert.match(english, /Stopped when computer use was paused/u);
    assert.match(english, /<code>cua_audio_source_missing<\/code>/u);
    assert.doesNotMatch(english, /<button|Audio capture did not finish|Any saved audio remains/u);
    globalThis.window = { localStorage: { getItem: () => 'zh-CN' } };
    const chinese = render();
    assert.match(chinese, /录音源文件已不存在，无法保存。/u);
    assert.match(chinese, /已随电脑操作暂停而停止/u);
    assert.doesNotMatch(chinese, /<button|音频采集未能正常完成|已保存的音频仍可播放/u);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
test('recording stop preempts ordinary management while full Stop still preempts export', async () => {
  const { createComputerUseManagement } = require(
    `${root}/src/features/settings/computerUseManagement.js`,
  );
  const requests = [],
    completed = [],
    errors = [];
  const manager = createComputerUseManagement({
    run: (operation, signal) =>
      new Promise((resolve, reject) => requests.push({ operation, signal, resolve, reject })),
    changed() {},
    completed: (value) => completed.push(value),
    failed: (value) => errors.push(value),
  });
  const ordinary = manager.manage({ action: 'permissions_status' });
  const audio = manager.manage({
    action: 'audio_stop',
    session_id: recording.session_id,
    recording_id: recording.recording_id,
  });
  assert.equal(requests[0].signal.aborted, true);
  await manager.manage({
    action: 'audio_stop',
    session_id: recording.session_id,
    recording_id: recording.recording_id,
  });
  assert.equal(requests.length, 2);
  const stop = manager.manage({ action: 'stop_all' });
  assert.equal(requests[1].signal.aborted, true);
  requests[2].resolve({ stopped: true });
  await stop;
  requests[1].reject(new Error('superseded export'));
  requests[0].resolve({ stale: true });
  await Promise.all([audio, ordinary]);
  assert.deepEqual(completed, [{ stopped: true }]);
  assert.deepEqual(errors, []);
  manager.dispose();
});
test('activity binds recordings to the selected conversation/run while settings retain owner history', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const device = require(`${root}/src/features/settings/ComputerUseDeviceProvider.js`);
  const { ComputerUseSettingsPage } = require(
    `${root}/src/features/settings/ComputerUseSettingsPage.js`,
  );
  const original = device.useComputerUseDevice;
  const previousWindow = globalThis.window;
  let current = recording;
  try {
    device.useComputerUseDevice = () => ({
      snapshot: {
        ...snapshot,
        recordings: [
          current,
          {
            ...recording,
            recording_id: 'other-recording',
            conversation_id: 'other-conversation',
            source: 'microphone',
          },
        ],
      },
      client: null,
      manage: async () => {},
      busy: false,
      stopping: false,
      mode: 'cloud',
      error: null,
    });
    const render = (Component, selection = { conversationId: 'conversation-1', runId: 'run-1' }) =>
      renderToStaticMarkup(
        React.createElement(I18nProvider, null, React.createElement(Component, selection)),
      );
    assert.match(render(device.ComputerUseActivity), /Stop recording/u);
    assert.equal(
      (render(device.ComputerUseActivity).match(/data-recording-status/g) ?? []).length,
      1,
    );
    assert.equal(
      render(device.ComputerUseActivity, { conversationId: 'conversation-1', runId: 'other-run' }),
      '',
    );
    assert.equal(
      render(device.ComputerUseActivity, { conversationId: 'conversation-1', runId: null }),
      '',
    );
    assert.equal(render(device.ComputerUseActivity, { conversationId: null, runId: null }), '');
    assert.match(render(ComputerUseSettingsPage), /Stop recording/u);
    globalThis.window = { localStorage: { getItem: () => 'zh-CN' } };
    assert.match(render(device.ComputerUseActivity), /正在录音/u);
    assert.match(render(ComputerUseSettingsPage), /停止录音/u);
    current = { ...recording, status: 'saved' };
    assert.match(render(device.ComputerUseActivity), /录音已保存/u);
    assert.match(
      render(device.ComputerUseActivity, { conversationId: 'conversation-1', runId: null }),
      /录音已保存/u,
    );
    assert.match(render(ComputerUseSettingsPage), /录音已保存/u);
  } finally {
    device.useComputerUseDevice = original;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
test('Electron tray exposes recording-only sessions and exact retry controls, then clears saved-only state', async () => {
  const Module = require('node:module');
  const original = Module._load;
  const created = [];
  class Tray {
    constructor() {
      created.push(this);
    }
    on() {}
    setToolTip() {}
    setContextMenu(menu) {
      this.menu = menu;
    }
    destroy() {
      this.destroyed = true;
    }
  }
  Module._load = function (name, ...rest) {
    return name === 'electron'
      ? {
          app: { getLocale: () => 'en-US' },
          Tray,
          Menu: { buildFromTemplate: (items) => items },
          nativeImage: { createFromBitmap: () => ({}) },
        }
      : original.call(this, name, ...rest);
  };
  try {
    const { createComputerUseActivityTray } = require(
      `${root}/apps/desktop/electron/main/computerUseActivityTray.js`,
    );
    const calls = [];
    const actions = {
      show() {},
      preview: async () => {
        throw new Error('no images');
      },
      manage: async (operation) => {
        calls.push(operation);
      },
    };
    const tray = createComputerUseActivityTray('win32');
    tray.update({ ...snapshot, recordings: [recording] }, actions);
    assert.equal(created.length, 1);
    assert.match(
      created[0].menu.find((item) => item.label?.includes('Microphone')).label,
      /Recording/u,
    );
    await created[0].menu.find((item) => item.label === 'Stop recording').click();
    assert.deepEqual(calls, [
      {
        action: 'audio_stop',
        session_id: recording.session_id,
        recording_id: recording.recording_id,
      },
    ]);
    tray.update({ ...snapshot, recordings: [{ ...recording, status: 'pending_export' }] }, actions);
    assert.equal(
      created[0].menu.some((item) => item.label === 'Stop recording'),
      false,
    );
    tray.update(
      {
        ...snapshot,
        recordings: [{ ...recording, status: 'failed', can_retry_export: true }],
      },
      actions,
    );
    await created[0].menu.find((item) => item.label === 'Retry saving recording').click();
    assert.deepEqual(calls[1], calls[0]);
    tray.update(
      {
        ...snapshot,
        recordings: [{ ...recording, status: 'saved', can_retry_export: false }],
      },
      actions,
    );
    assert.equal(created[0].destroyed, true);
    tray.hide();
  } finally {
    Module._load = original;
  }
});
