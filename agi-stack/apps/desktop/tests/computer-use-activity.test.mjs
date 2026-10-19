import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  ComputerUseActivityMonitor,
} = require('/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/computerUseActivityMonitor.js');
const {
  computerUseSessionView,
  computerUseImageIdentity,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/computerUsePresentationModel.js');
const base = {
  plugin_id: 'memstack-computer-use',
  device_id: 'device',
  helper_available: true,
  scope: { tenant_id: 'tenant', project_id: 'project' },
  instance: { installed: true, enabled: true, revision: 1 },
  grants: [],
  pending: [],
  sessions: [],
};
const args = (project = 'project') => ({
  input: {
    mode: 'local',
    tenant_id: 'tenant',
    project_id: project,
    credential: 'fixture-only',
    operation: { action: 'status' },
  },
});

test('Stop preempts a pending management request and ignores its late response or failure', async () => {
  const {
    createComputerUseManagement,
  } = require('/tmp/agistack-desktop-test-dist/src/features/settings/computerUseManagement.js');
  for (const outcome of ['resolve', 'reject']) {
    const requests = [];
    const results = [];
    const errors = [];
    const states = [];
    const management = createComputerUseManagement({
      run: (operation, signal) =>
        new Promise((resolve, reject) => {
          requests.push({ operation, signal, resolve, reject });
        }),
      changed: (busy, stopping) => states.push({ busy, stopping }),
      completed: (snapshot) => results.push(snapshot),
      failed: (error) => errors.push(error),
    });
    const pending = management.manage({ action: 'permissions_status' });
    await management.manage({ action: 'pause', session_id: 'session' });
    assert.equal(requests.length, 1, 'ordinary operations remain serialized');
    const stopped = management.manage({ action: 'stop_all' });
    assert.equal(requests[0].signal.aborted, true);
    assert.deepEqual(requests[1].operation, { action: 'stop_all' });
    await management.manage({ action: 'stop_all' });
    await management.manage({ action: 'stop', session_id: 'session' });
    await management.manage({ action: 'resume', session_id: 'session' });
    assert.equal(requests.length, 2, 'an in-flight Stop cannot be duplicated or bypassed');
    const refreshGeneration = management.generation();
    assert.equal(management.acceptsRefresh(refreshGeneration), false);
    let completeRefresh;
    const lateRefresh = new Promise((resolve) => {
      completeRefresh = resolve;
    }).then((snapshot) => {
      if (management.acceptsRefresh(refreshGeneration)) results.push(snapshot);
    });
    const snapshot = { ...base, sessions: [] };
    requests[1].resolve(snapshot);
    await stopped;
    completeRefresh({ ...base, pending: ['stale poll during Stop'] });
    await lateRefresh;
    if (outcome === 'resolve') requests[0].resolve({ ...base, pending: ['stale'] });
    else requests[0].reject(new Error('stale_native_failure'));
    await pending;
    assert.deepEqual(results, [snapshot]);
    assert.deepEqual(errors, []);
    assert.equal(management.generation(), 3);
    assert.equal(management.acceptsRefresh(refreshGeneration), false);
    assert.equal(management.acceptsRefresh(management.generation()), true);
    assert.deepEqual(states, [
      { busy: true, stopping: false },
      { busy: true, stopping: true },
      { busy: false, stopping: false },
    ]);
  }
});

test('single-session Stop preempts a normal operation; scope disposal rejects late completion', async () => {
  const {
    createComputerUseManagement,
  } = require('/tmp/agistack-desktop-test-dist/src/features/settings/computerUseManagement.js');
  const requests = [];
  const results = [];
  const errors = [];
  const management = createComputerUseManagement({
    run: (operation, signal) =>
      new Promise((resolve, reject) => {
        requests.push({ operation, signal, resolve, reject });
      }),
    changed() {},
    completed: (snapshot) => results.push(snapshot),
    failed: (error) => errors.push(error),
  });
  const pending = management.manage({ action: 'pause', session_id: 'session' });
  const stopped = management.manage({ action: 'stop', session_id: 'session' });
  assert.equal(requests[0].signal.aborted, true);
  assert.deepEqual(requests[1].operation, { action: 'stop', session_id: 'session' });
  requests[0].resolve(base);
  await pending;
  requests[1].reject(new Error('cua_native_stop_failed'));
  await stopped;
  assert.deepEqual(errors, ['cua_native_stop_failed']);
  const next = management.manage({ action: 'stop_all' });
  management.dispose();
  assert.equal(requests[2].signal.aborted, true);
  requests[2].resolve(base);
  await next;
  assert.deepEqual(results, []);
});

test('native activity events cannot replace Stop with an older management or concurrent status reply', async () => {
  const requests = [];
  const emitted = [];
  const monitor = new ComputerUseActivityMonitor({
    invoke: () => new Promise((resolve) => requests.push(resolve)),
    emit: (_owner, snapshot) => emitted.push(snapshot),
    show() {},
    surface: { update() {}, hide() {} },
  });
  const active = { ...base, sessions: [{ session_id: 'native' }] };
  try {
    const initial = monitor.track(1, args());
    requests[0](active);
    await initial;
    const approve = monitor.track(1, {
      input: { ...args().input, operation: { action: 'approve' } },
    });
    const stop = monitor.track(1, {
      input: { ...args().input, operation: { action: 'stop_all' } },
    });
    const statusDuringStop = monitor.track(1, args());
    requests[2](base);
    await stop;
    requests[3](active);
    await statusDuringStop;
    requests[1](active);
    await approve;
    assert.deepEqual(emitted, [active, base]);
  } finally {
    monitor.clear();
  }
});

test('a new owner scope invalidates a pending management receipt', async () => {
  const requests = [];
  const emitted = [];
  const monitor = new ComputerUseActivityMonitor({
    invoke: () => new Promise((resolve) => requests.push(resolve)),
    emit: (owner, snapshot) => emitted.push({ owner, snapshot }),
    show() {},
    surface: { update() {}, hide() {} },
  });
  try {
    const old = monitor.track(1, { input: { ...args().input, operation: { action: 'approve' } } });
    const next = monitor.track(2, args('other-project'));
    const snapshot = { ...base, scope: { tenant_id: 'tenant', project_id: 'other-project' } };
    requests[1](snapshot);
    await next;
    requests[0](base);
    await old;
    assert.deepEqual(emitted, [{ owner: 2, snapshot }]);
  } finally {
    monitor.clear();
  }
});

test('owner cleanup invalidates its first pending management request before it has a snapshot', async () => {
  let resolve;
  const emitted = [];
  const monitor = new ComputerUseActivityMonitor({
    invoke: () =>
      new Promise((done) => {
        resolve = done;
      }),
    emit: (...event) => emitted.push(event),
    show() {},
    surface: { update() {}, hide() {} },
  });
  const pending = monitor.track(1, {
    input: { ...args().input, operation: { action: 'stop_all' } },
  });
  monitor.clear(1);
  resolve(base);
  await pending;
  assert.deepEqual(emitted, []);
  monitor.clear();
});

test('an older poll failure cannot hide the surface while Stop is pending', async () => {
  const requests = [];
  let hidden = 0;
  const monitor = new ComputerUseActivityMonitor({
    invoke: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
    emit() {},
    show() {},
    surface: {
      update() {},
      hide() {
        hidden++;
      },
    },
  });
  try {
    const initial = monitor.track(1, args());
    requests[0].resolve({ ...base, sessions: [{ session_id: 'native' }] });
    await initial;
    await new Promise((resolve) => setTimeout(resolve, 1100));
    assert.equal(requests.length, 2);
    const stopped = monitor.track(1, {
      input: { ...args().input, operation: { action: 'stop_all' } },
    });
    requests[1].reject(new Error('old_status_failed'));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(hidden, 0);
    requests[2].resolve(base);
    await stopped;
  } finally {
    monitor.clear();
  }
});

test('pause and resume use declared state, exact session membership and terminal status', () => {
  const paused = {
    session_id: 'native-child',
    conversation_id: 'child',
    run_id: 'run',
    stopped: false,
    presentation: {
      phase: 'paused',
      can_resume: false,
      resume_blocked_reason: 'cloud_resume_unavailable',
    },
  };
  assert.equal(
    computerUseSessionView({ ...base, pending: [{ session_id: 'native-child' }] }, paused).phase,
    'paused'
  );
  assert.equal(computerUseSessionView(base, paused).can_resume, false);
  assert.equal(
    computerUseSessionView(base, {
      ...paused,
      stopped: true,
      presentation: { phase: 'paused', can_resume: true },
    }).can_resume,
    false
  );
  assert.equal(
    computerUseSessionView(
      { ...base, pending: [{ session_id: 'sibling' }] },
      { ...paused, presentation: undefined }
    ).phase,
    'idle'
  );
  assert.equal(
    computerUseImageIdentity({
      artifact_id: 'cua-image-abcd',
      mime_type: 'image/png',
    }),
    'cua-image-abcd'
  );
  assert.equal(
    computerUseImageIdentity({
      artifact_id: 'file:///private/icon.png',
      mime_type: 'image/png',
    }),
    null
  );
  assert.equal(
    computerUseImageIdentity({
      artifact_id: 'cua-image-abcd',
      mime_type: 'text/html',
    }),
    null
  );
});

test('the native monitor binds menu actions to the authenticated owner scope and rejects stale callbacks', async () => {
  const emitted = [];
  const surfaces = [];
  const requests = [];
  const monitor = new ComputerUseActivityMonitor({
    invoke: async (input) => {
      requests.push(input);
      return {
        ...base,
        scope: { ...base.scope, project_id: input.input.project_id },
      };
    },
    emit: (owner, snapshot, mode) => emitted.push({ owner, snapshot, mode }),
    show() {},
    surface: {
      update: (snapshot, actions) => surfaces.push({ snapshot, actions }),
      hide() {},
    },
  });
  try {
    await monitor.track(7, args());
    const old = surfaces[0].actions;
    await monitor.track(7, args('other'));
    await assert.rejects(old.manage({ action: 'stop_all' }), /scope_expired/u);
    assert.equal(requests.length, 2);
    assert.equal(emitted.at(-1).mode, 'local');
    assert.equal(emitted.at(-1).owner, 7);
    assert.equal(JSON.stringify(emitted).includes('fixture-only'), false);
    await surfaces.at(-1).actions.manage({ action: 'pause', session_id: 'native' });
    assert.equal(requests.at(-1).input.project_id, 'other');
    assert.equal(requests.at(-1).input.operation.session_id, 'native');
  } finally {
    monitor.clear();
  }
});

test('an old native response cannot publish after a new scope or shutdown', async () => {
  let release;
  const emitted = [];
  const monitor = new ComputerUseActivityMonitor({
    invoke: (input) =>
      input.input.project_id === 'project'
        ? new Promise((resolve) => {
            release = resolve;
          })
        : Promise.resolve({
            ...base,
            scope: { ...base.scope, project_id: 'other' },
          }),
    emit: (_owner, snapshot) => emitted.push(snapshot),
    show() {},
    surface: { update() {}, hide() {} },
  });
  const old = monitor.track(1, args());
  await monitor.track(1, args('other'));
  release(base);
  await old;
  assert.deepEqual(
    emitted.map((value) => value.scope.project_id),
    ['other']
  );
  monitor.clear();
  const late = monitor.track(1, args());
  monitor.clear();
  release(base);
  await late;
  assert.equal(emitted.length, 1);
});

test('the main monitor refreshes active native state without a visible renderer polling it', async () => {
  let count = 0;
  const emitted = [];
  const active = {
    ...base,
    sessions: [
      {
        session_id: 'native',
        conversation_id: 'conversation',
        run_id: 'run',
        stopped: false,
        presentation: { phase: 'acting' },
      },
    ],
  };
  const monitor = new ComputerUseActivityMonitor({
    invoke: async () => {
      count++;
      return count === 1
        ? active
        : {
            ...active,
            sessions: [
              {
                ...active.sessions[0],
                presentation: { phase: 'paused', can_resume: true },
              },
            ],
          };
    },
    emit: (_owner, snapshot) => emitted.push(snapshot),
    show() {},
    surface: { update() {}, hide() {} },
  });
  try {
    await monitor.track(1, args());
    await new Promise((resolve) => setTimeout(resolve, 1100));
    assert.equal(emitted.at(-1).sessions[0].presentation.phase, 'paused');
  } finally {
    monitor.clear();
  }
});

test('recent preview components expose app, window identity and observation time without native paths', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
  const {
    ComputerUseTargetPreview,
  } = require('/tmp/agistack-desktop-test-dist/src/features/settings/ComputerUseTargetPreview.js');
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ComputerUseTargetPreview, {
        client: null,
        recent: true,
        presentation: {
          phase: 'stopped',
          target: {
            app_id: 'fixture',
            display_name: 'Fixture',
            identity_digest: 'identity',
            window_id: 'window-4',
            window_title: 'Owned fixture window',
          },
          preview: {
            artifact_id: 'cua-image-abcd',
            mime_type: 'image/png',
            observed_at: '2026-10-14T01:00:00Z',
          },
        },
      })
    )
  );
  assert.match(html, /Owned fixture window/u);
  assert.match(html, /window-4/u);
  assert.match(html, /dateTime="2026-10-14T01:00:00Z"/u);
  assert.doesNotMatch(html, /file:|data:image/u);
});

test('the real activity controls resume only a native-declared resumable session', () => {
  const React = require('react');
  const jsx = require('react/jsx-runtime');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
  const device = require('/tmp/agistack-desktop-test-dist/src/features/settings/ComputerUseDeviceProvider.js');
  const original = device.useComputerUseDevice;
  const originalJsx = jsx.jsx;
  const originalJsxs = jsx.jsxs;
  const calls = [];
  const buttons = [];
  const previousWindow = globalThis.window;
  const intercept =
    (delegate) =>
    (type, props, ...rest) => {
      if (type === 'button') buttons.push(props);
      return delegate(type, props, ...rest);
    };
  try {
    jsx.jsx = intercept(originalJsx);
    jsx.jsxs = intercept(originalJsxs);
    let canResume = true;
    let busy = false;
    let stopping = false;
    let error = null;
    device.useComputerUseDevice = () => ({
      client: null,
      busy,
      stopping,
      error,
      manage: (operation) => {
        calls.push(operation);
        return Promise.resolve();
      },
      snapshot: {
        ...base,
        sessions: [
          {
            session_id: 'exact-native-session',
            conversation_id: 'conversation',
            run_id: 'run',
            stopped: false,
            presentation: {
              phase: 'paused',
              can_resume: canResume,
              resume_blocked_reason: 'cloud_resume_unavailable',
            },
          },
        ],
      },
    });
    const render = () =>
      renderToStaticMarkup(
        React.createElement(I18nProvider, null, React.createElement(device.ComputerUseActivity, {
          conversationId: 'conversation', runId: 'run',
        }))
      );
    const html = render();
    assert.match(html, /Paused/u);
    assert.match(html, /Resume computer use/u);
    buttons.find((button) => button.children === 'Resume computer use').onClick();
    assert.deepEqual(calls, [{ action: 'resume', session_id: 'exact-native-session' }]);
    busy = true;
    error = 'cua_native_stop_failed';
    buttons.length = 0;
    const failed = render();
    assert.match(failed, /role="alert"/u);
    assert.match(failed, /The device operation could not complete/u);
    assert.match(failed, /cua_native_stop_failed/u);
    assert.equal(
      buttons.find((button) => button.children === 'Resume computer use').disabled,
      true
    );
    const stopButtons = buttons.filter((button) => button.children === 'Stop computer use');
    assert.equal(stopButtons.length, 1);
    assert.ok(stopButtons.every((button) => !button.disabled));
    stopButtons[0].onClick();
    assert.deepEqual(calls.at(-1), { action: 'stop', session_id: 'exact-native-session' });
    stopping = true;
    buttons.length = 0;
    render();
    assert.ok(
      buttons
        .filter((button) => button.children === 'Stop computer use')
        .every((button) => button.disabled)
    );
    stopping = false;
    globalThis.window = { localStorage: { getItem: () => 'zh-CN' } };
    assert.match(render(), /设备操作未能完成。/u);
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    canResume = false;
    buttons.length = 0;
    const blocked = render();
    assert.doesNotMatch(blocked, /Resume computer use/u);
    assert.match(blocked, /cloud_resume_unavailable/u);
    const {
      ComputerUseSettingsPage,
    } = require('/tmp/agistack-desktop-test-dist/src/features/settings/ComputerUseSettingsPage.js');
    buttons.length = 0;
    renderToStaticMarkup(
      React.createElement(I18nProvider, null, React.createElement(ComputerUseSettingsPage))
    );
    assert.equal(buttons.find((button) => button.children === 'Stop computer use').disabled, false);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    device.useComputerUseDevice = original;
    jsx.jsx = originalJsx;
    jsx.jsxs = originalJsxs;
  }
});

test('macOS never creates a second Electron tray and Windows callbacks use native management', async () => {
  const Module = require('node:module');
  const original = Module._load;
  const created = [];
  class Tray {
    constructor() {
      created.push(this);
    }
    on(_event, callback) {
      this.show = callback;
    }
    setToolTip() {}
    setContextMenu(menu) {
      this.menu = menu;
    }
    destroy() {
      this.destroyed = true;
    }
  }
  const image = (data = 'tray') => ({
    data,
    isEmpty: () => false,
    resize(size) {
      return { data, size };
    },
  });
  Module._load = function (name, ...rest) {
    return name === 'electron'
      ? {
          app: { getLocale: () => 'en' },
          Tray,
          Menu: { buildFromTemplate: (items) => items },
          nativeImage: {
            createFromBitmap: () => image(),
            createFromDataURL: (data) => image(data),
          },
        }
      : original.call(this, name, ...rest);
  };
  try {
    const {
      createComputerUseActivityTray,
    } = require('/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/computerUseActivityTray.js');
    const actions = [];
    const previews = new Map();
    let shown = 0;
    const native = {
      show() {
        shown++;
      },
      manage: async (operation) => {
        actions.push(operation);
      },
      preview: (artifactId) => new Promise((resolve) => previews.set(artifactId, resolve)),
    };
    const active = {
      ...base,
      sessions: [
        {
          session_id: 'native',
          conversation_id: 'conversation',
          run_id: 'run',
          stopped: false,
          presentation: {
            phase: 'paused',
            can_resume: true,
            target: {
              display_name: 'Fixture',
              window_title: 'First authorized window',
            },
            app_icon: { artifact_id: 'cua-image-1111', mime_type: 'image/png' },
            preview: {
              artifact_id: 'cua-image-aaaa',
              mime_type: 'image/png',
              observed_at: '2026-10-14T01:00:00Z',
            },
          },
        },
        {
          session_id: 'native-second',
          conversation_id: 'conversation-second',
          run_id: 'run-second',
          stopped: false,
          presentation: {
            phase: 'paused',
            can_resume: false,
            resume_blocked_reason: 'cloud_resume_unavailable',
            target: {
              display_name: 'Second fixture',
              window_title: 'Second authorized window',
            },
            app_icon: { artifact_id: 'cua-image-2222', mime_type: 'image/png' },
            preview: {
              artifact_id: 'cua-image-bbbb',
              mime_type: 'image/png',
            },
          },
        },
      ],
    };
    createComputerUseActivityTray('darwin').update(active, native);
    assert.equal(created.length, 0);
    const tray = createComputerUseActivityTray('win32');
    tray.update(active, native);
    assert.equal(previews.size, 4);
    const flush = () => new Promise((resolve) => setImmediate(resolve));
    for (const [id, data] of [
      ['cua-image-bbbb', 'second-preview'],
      ['cua-image-2222', 'second-icon'],
      ['cua-image-aaaa', 'first-preview'],
      ['cua-image-1111', 'first-icon'],
    ]) {
      previews.get(id)(data);
      await flush();
    }
    const menu = created[0].menu;
    assert.equal(
      menu.find((item) => item.label?.includes('First authorized window')).icon.data,
      'first-icon'
    );
    assert.equal(
      menu.find((item) => item.label?.includes('Second authorized window')).icon.data,
      'second-icon'
    );
    assert.equal(menu.filter((item) => item.label === 'Resume').length, 1);
    assert.equal(
      menu.find((item) => item.label?.includes('cloud_resume_unavailable')).enabled,
      false
    );
    const thumbnails = menu.filter((item) =>
      item.label?.startsWith('Latest authorized observation')
    );
    assert.equal(thumbnails.length, 2);
    assert.equal(thumbnails[0].icon.data, 'first-preview');
    assert.equal(thumbnails[1].icon.data, 'second-preview');
    assert.equal(thumbnails[0].icon.size.width, 64);
    thumbnails[1].click();
    assert.equal(shown, 1);
    created[0].menu.find((item) => item.label === 'Resume').click();
    assert.deepEqual(actions, [{ action: 'resume', session_id: 'native' }]);
    tray.update(active, native);
    const staleIcon = previews.get('cua-image-1111');
    tray.update(
      {
        ...active,
        sessions: [
          {
            ...active.sessions[1],
            presentation: {
              ...active.sessions[1].presentation,
              app_icon: undefined,
              preview: undefined,
            },
          },
        ],
      },
      native
    );
    staleIcon('stale-first-icon');
    await flush();
    assert.equal(
      created[0].menu.some((item) => item.icon?.data === 'stale-first-icon'),
      false
    );
    assert.equal(
      created[0].menu.some((item) => item.label?.includes('First authorized window')),
      false
    );
    tray.update(active, native);
    const beforeHide = created[0].menu;
    const hiddenPreview = previews.get('cua-image-aaaa');
    tray.update({ ...base, sessions: [] }, native);
    hiddenPreview('stale-hidden-preview');
    await flush();
    assert.equal(created[0].destroyed, true);
    assert.equal(created[0].menu, beforeHide);
    const linux = createComputerUseActivityTray('linux');
    linux.update(active, native);
    previews.get('cua-image-2222')('linux-second-icon');
    await flush();
    assert.equal(created.length, 2);
    assert.equal(
      created[1].menu.find((item) => item.label?.includes('Second authorized window')).icon.data,
      'linux-second-icon'
    );
    created[1].menu.find((item) => item.label === 'Show Computer Use').click();
    assert.equal(shown, 2);
    linux.hide();
    assert.equal(created[1].destroyed, true);
  } finally {
    Module._load = original;
  }
});
