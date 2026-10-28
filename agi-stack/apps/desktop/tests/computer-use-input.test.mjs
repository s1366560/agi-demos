import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const root = '/tmp/agistack-desktop-test-dist';
const { parseComputerUseInput, parseComputerUseInputEvent } = require(
  `${root}/src/api/computerUseInput.js`,
);
const { isComputerUseSnapshotForScope } = require(`${root}/src/api/computerUseContractV2.js`);
const { createComputerUseInputStore } = require(
  `${root}/src/features/settings/computerUseInputStore.js`,
);
const { ComputerUseInputMonitor } = require(
  `${root}/apps/desktop/electron/main/computerUseInputMonitor.js`,
);
const { createComputerUseManagement, createComputerUseSnapshotUpdates } = require(
  `${root}/src/features/settings/computerUseManagement.js`,
);
const {
  computerUseInputMatchesPreview,
  computerUseCursorPosition,
  computerUseContainedImageBounds,
  computerUseHeldLabels,
} = require(`${root}/src/features/settings/computerUseInputPresentation.js`);
const scope = { mode: 'local', tenant_id: 'tenant', project_id: 'project' };
const input = (overrides = {}) => ({
  ...scope,
  conversation_id: 'conversation',
  run_id: 'run',
  session_id: 'session',
  input_mode: 'background',
  input_generation: 'generation-a',
  sequence: 1,
  updated_at: 1,
  phase: 'moving',
  target_pid: 42,
  target_window_id: 'window-4',
  virtual_cursor: {
    x: 200,
    y: 150,
    width: 400,
    height: 300,
    window_id: 'window-4',
  },
  held_keys: [],
  held_buttons: [],
  evidence: 'dispatched',
  ...overrides,
});
const session = (overrides = {}) => ({
  session_id: 'session',
  conversation_id: 'conversation',
  run_id: 'run',
  stopped: false,
  input_mode: 'background',
  input_generation: 'generation-a',
  presentation: {
    phase: 'acting',
    target: {
      app_id: 'app',
      display_name: 'App',
      process_id: 42,
      identity_digest: 'digest',
      window_id: 'window-4',
    },
  },
  ...overrides,
});
const snapshot = (sessions = [session()]) => ({
  plugin_id: 'memstack-computer-use',
  device_id: 'device',
  helper_available: true,
  scope: { tenant_id: scope.tenant_id, project_id: scope.project_id },
  instance: {
    installed: true,
    enabled: true,
    revision: 3,
    input_mode: 'background',
  },
  input_support: {
    background: { supported: true, reason: null },
    foreground: { supported: true, reason: null },
  },
  grants: [],
  pending: [],
  sessions,
});
const event = (value) => ({ type: 'computer_use_input', input: value });
function harness() {
  const frames = new Map();
  let next = 0;
  const store = createComputerUseInputStore(scope, {
    request: (callback) => {
      frames.set(++next, callback);
      return next;
    },
    cancel: (id) => frames.delete(id),
  });
  store.updateSnapshot(snapshot());
  return {
    store,
    frames,
    flush() {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback());
    },
  };
}

test('native input parsing strips undeclared content and validates bounded geometry and codes', () => {
  const parsed = parseComputerUseInput({
    ...input(),
    typed_text: 'never retain',
    held_keys: [54, 54],
    virtual_cursor: { ...input().virtual_cursor, text: 'private' },
  });
  assert.deepEqual(parsed.held_keys, [54]);
  assert.equal('typed_text' in parsed, false);
  assert.equal('text' in parsed.virtual_cursor, false);
  for (const changes of [
    { mode: 'remote' },
    { input_mode: 'automatic' },
    { input_generation: '' },
    { sequence: -1 },
    { sequence: NaN },
    { sequence: Number.MAX_SAFE_INTEGER + 1 },
    { updated_at: Infinity },
    { held_keys: [65536] },
    { held_buttons: [32] },
    { evidence: 'success' },
    { target_window_id: 'different' },
    { virtual_cursor: { ...input().virtual_cursor, width: 0 } },
    { virtual_cursor: { ...input().virtual_cursor, x: Infinity } },
  ])
    assert.equal(parseComputerUseInput(input(changes)), null, JSON.stringify(changes));
  assert.equal(parseComputerUseInputEvent({ type: 'untrusted', input: input() }), null);
  assert.equal(
    parseComputerUseInputEvent({ type: 'computer_use_input_reset', ...scope }).type,
    'computer_use_input_reset',
  );
});

test('input capabilities fail closed when a snapshot contains malformed native support', () => {
  const owner = { tenantId: 'tenant', projectId: 'project' };
  assert.equal(isComputerUseSnapshotForScope(snapshot(), owner), true);
  assert.equal(
    isComputerUseSnapshotForScope(
      {
        ...snapshot(),
        input_support: {
          background: { supported: 'true', reason: null },
          foreground: { supported: true, reason: null },
        },
      },
      owner,
    ),
    false,
  );
  assert.equal(
    isComputerUseSnapshotForScope(snapshot([session({ input_generation: 123 })]), owner),
    false,
  );
});

test('bursts coalesce to one update per frame and do not notify unrelated sessions', () => {
  const h = harness();
  let updates = 0;
  let other = 0;
  const stop = h.store.subscribe('session', () => updates++);
  h.store.subscribe('another-session', () => other++);
  for (let sequence = 1; sequence <= 100; sequence++) h.store.receive(event(input({ sequence })));
  assert.equal(h.frames.size, 1);
  assert.equal(updates, 0);
  h.flush();
  assert.equal(updates, 1);
  assert.equal(other, 0);
  assert.equal(h.store.getSnapshot('session').sequence, 100);
  h.store.receive(event(input({ sequence: 100 })));
  h.store.receive(event(input({ sequence: 99 })));
  h.flush();
  assert.equal(updates, 1);
  stop();
  h.store.receive(event(input({ sequence: 101 })));
  h.flush();
  assert.equal(updates, 1);
});

test('scope, run and session membership reject foreign samples and foreign clears', () => {
  const h = harness();
  for (const changes of [
    { project_id: 'other' },
    { mode: 'cloud' },
    { tenant_id: 'other' },
    { run_id: 'other' },
    { conversation_id: 'other' },
    { session_id: 'other' },
    { input_mode: 'foreground' },
  ])
    h.store.receive(event(input(changes)));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.receive(event(input()));
  h.flush();
  h.store.receive({
    type: 'computer_use_input_reset',
    ...scope,
    project_id: 'other',
  });
  assert.ok(h.store.getSnapshot('session'));
  h.store.receive({ type: 'computer_use_input_reset', ...scope });
  assert.equal(h.store.getSnapshot('session'), null);
});

test('pause clears pending frames immediately and the same generation cannot reappear after resume', () => {
  const h = harness();
  h.store.receive(event(input()));
  h.store.willManage({ action: 'pause', session_id: 'session' });
  assert.equal(h.frames.size, 0);
  h.store.receive(event(input({ sequence: 2 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.updateSnapshot(snapshot([session({ presentation: { phase: 'paused' } })]));
  h.store.updateSnapshot(snapshot([session({ input_generation: 'generation-b' })]));
  h.store.receive(event(input({ sequence: 999 })));
  h.store.receive(event(input({ input_generation: 'generation-b' })));
  h.flush();
  assert.equal(h.store.getSnapshot('session').input_generation, 'generation-b');
  h.store.receive(event(input({ input_generation: 'generation-b', sequence: 2, phase: 'paused' })));
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.receive(event(input({ input_generation: 'generation-b', sequence: 3 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
});

test('a future generation waits for the authoritative snapshot and released input keeps its cursor', () => {
  const h = harness();
  h.store.receive(event(input({ input_generation: 'generation-b', phase: 'released' })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.updateSnapshot(snapshot([session({ input_generation: 'generation-b' })]));
  h.flush();
  assert.equal(h.store.getSnapshot('session').phase, 'released');
  h.store.willManage({ action: 'set_input_mode', input_mode: 'foreground' });
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.updateSnapshot(snapshot([]));
  h.store.receive(event(input({ input_generation: 'generation-b', sequence: 4 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
});

test('stop, errors, revocation and disposal never leave held input or pending pointer frames', () => {
  for (const phase of ['paused', 'stopped', 'error']) {
    const h = harness();
    h.store.receive(event(input({ held_keys: [55], held_buttons: [0] })));
    h.flush();
    h.store.receive(event(input({ sequence: 2, phase })));
    assert.equal(h.store.getSnapshot('session'), null);
    assert.equal(h.frames.size, 0);
  }
  const h = harness();
  h.store.receive(event(input()));
  h.flush();
  h.store.updateSnapshot(snapshot([session({ presentation: { phase: 'awaiting_permission' } })]));
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.dispose();
  h.flush();
  h.store.receive(event(input({ sequence: 3 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
});

test('terminal samples from an unbound generation cannot clear current input', () => {
  const h = harness();
  const sent = [];
  const monitor = new ComputerUseInputMonitor((owner, value) => sent.push(value));
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  h.store.receive(event(input()));
  h.flush();
  monitor.receive(input());
  for (const phase of ['paused', 'stopped', 'error']) {
    const unbound = input({
      input_generation: 'unbound-generation',
      phase,
      sequence: 5,
    });
    h.store.receive(event(unbound));
    monitor.receive(unbound);
  }
  assert.equal(h.store.getSnapshot('session').input_generation, 'generation-a');
  assert.equal(sent.length, 1);
  h.store.receive(event(input({ phase: 'error', sequence: 100 })));
  h.store.receive(event(input({ sequence: 99 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.receive(event(input({ sequence: 101 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session').sequence, 101);
});

test('a pending generation preserves its highest sequence until metadata binds it', () => {
  const h = harness();
  const sent = [];
  const monitor = new ComputerUseInputMonitor((owner, value) => sent.push(value));
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  for (const sequence of [10, 9, 8]) {
    const value = input({ input_generation: 'generation-b', sequence });
    h.store.receive(event(value));
    monitor.receive(value);
  }
  const next = snapshot([session({ input_generation: 'generation-b' })]);
  h.store.updateSnapshot(next);
  h.flush();
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, next);
  assert.equal(h.store.getSnapshot('session').sequence, 10);
  assert.equal(sent.at(-1).input.sequence, 10);
});

test('startup samples wait for scoped session metadata in main and the renderer', () => {
  const h = harness();
  h.store.updateSnapshot(snapshot([]));
  const sent = [];
  const monitor = new ComputerUseInputMonitor((owner, value) => {
    sent.push(value);
    h.store.receive(value);
  });
  monitor.receive(input({ sequence: 10 }));
  assert.equal(sent.length, 0);
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot([]));
  monitor.receive(input({ sequence: 11 }));
  assert.equal(sent.length, 0);
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  assert.equal(sent.length, 1);
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.updateSnapshot(snapshot());
  h.flush();
  assert.equal(h.store.getSnapshot('session').sequence, 11);
});

test('missing binding metadata clears the view without retiring a still-current generation', () => {
  const h = harness();
  const sent = [];
  const monitor = new ComputerUseInputMonitor((owner, value) => sent.push(value));
  const bind = (value) => {
    h.store.updateSnapshot(value);
    monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
  };
  bind(snapshot());
  h.store.receive(event(input()));
  h.flush();
  monitor.receive(input());
  bind(snapshot([session({ input_generation: null })]));
  assert.equal(h.store.getSnapshot('session'), null);
  h.store.receive(event(input({ sequence: 2 })));
  monitor.receive(input({ sequence: 2 }));
  assert.equal(sent.length, 1);
  bind(snapshot());
  h.flush();
  assert.equal(h.store.getSnapshot('session').sequence, 2);
  assert.equal(sent.at(-1).input.sequence, 2);
});

test('permission, focus and error recovery reuse the generation while keeping old frames hidden', () => {
  for (const phase of ['awaiting_permission', 'focus_required', 'error']) {
    const h = harness();
    const sent = [];
    const monitor = new ComputerUseInputMonitor((owner, value) => sent.push(value));
    const bind = (value) => {
      h.store.updateSnapshot(value);
      monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
    };
    bind(snapshot());
    h.store.receive(event(input()));
    h.flush();
    monitor.receive(input());
    bind(snapshot([session({ presentation: { phase } })]));
    h.store.receive(event(input({ sequence: 2 })));
    monitor.receive(input({ sequence: 2 }));
    h.flush();
    assert.equal(h.store.getSnapshot('session'), null);
    assert.equal(sent.length, 1);
    bind(snapshot());
    h.store.receive(event(input({ sequence: 3 })));
    h.flush();
    monitor.receive(input({ sequence: 3 }));
    assert.equal(h.store.getSnapshot('session').sequence, 3);
    assert.equal(sent.at(-1).input.sequence, 3);
  }
});

test('recovery input arriving before idle metadata is retained through both IPC consumers', () => {
  for (const phase of ['awaiting_permission', 'focus_required', 'error', 'paused']) {
    const h = harness();
    const monitor = new ComputerUseInputMonitor((owner, value) => h.store.receive(value));
    const bind = (value) => {
      monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
      h.store.updateSnapshot(value);
    };
    const blocked = snapshot([session({ presentation: { phase } })]);
    bind(blocked);
    const generation = phase === 'paused' ? 'generation-b' : 'generation-a';
    for (const sequence of [10, 9])
      monitor.receive(input({ input_generation: generation, sequence, phase: 'released' }));
    bind(blocked);
    h.flush();
    assert.equal(h.store.getSnapshot('session'), null);
    bind(snapshot([session({ input_generation: generation })]));
    h.flush();
    assert.equal(h.store.getSnapshot('session').sequence, 10);
    assert.equal(h.store.getSnapshot('session').phase, 'released');
    monitor.clear();
  }
});

test('stop discards buffered recovery input and never revives it from a late active snapshot', () => {
  const h = harness();
  const monitor = new ComputerUseInputMonitor((owner, value) => h.store.receive(value));
  const bind = (value) => {
    monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
    h.store.updateSnapshot(value);
  };
  bind(snapshot([session({ presentation: { phase: 'awaiting_permission' } })]));
  monitor.receive(input({ sequence: 10, phase: 'released' }));
  monitor.willManage({ action: 'stop', session_id: 'session' });
  h.store.willManage({ action: 'stop', session_id: 'session' });
  bind(snapshot([session({ stopped: true, presentation: { phase: 'stopped' } })]));
  monitor.receive(input({ sequence: 11, phase: 'released' }));
  bind(snapshot());
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
});

test('a rejected mode change keeps the live generation available for newer receipts', async () => {
  const h = harness();
  const errors = [];
  const monitor = new ComputerUseInputMonitor((owner, value) => h.store.receive(value));
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  monitor.receive(input());
  h.flush();
  const management = createComputerUseManagement({
    run: async (operation) => {
      h.store.willManage(operation);
      monitor.willManage(operation);
      throw new Error('cua_instance_revision_conflict');
    },
    changed: () => {},
    completed: (value) => h.store.updateSnapshot(value),
    failed: (error) => errors.push(error),
  });
  await management.manage({
    action: 'set_input_mode',
    input_mode: 'foreground',
    expected_revision: 2,
  });
  assert.deepEqual(errors, ['cua_instance_revision_conflict']);
  assert.equal(h.store.getSnapshot('session'), null);
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  h.store.updateSnapshot(snapshot());
  monitor.receive(input({ sequence: 2 }));
  h.flush();
  assert.equal(h.store.getSnapshot('session').sequence, 2);
  monitor.receive(input({ sequence: 1 }));
  h.flush();
  assert.equal(h.store.getSnapshot('session').sequence, 2);
});

for (const action of ['disable', 'uninstall']) {
  test(`a rejected ${action} preserves the live generation after a fresh active snapshot`, async () => {
    const h = harness();
    const errors = [];
    const monitor = new ComputerUseInputMonitor((owner, value) => h.store.receive(value));
    const bind = (value) => {
      monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
      h.store.updateSnapshot(value);
    };
    const management = createComputerUseManagement({
      run: async (operation) => {
        h.store.willManage(operation);
        monitor.willManage(operation);
        throw new Error('cua_instance_revision_conflict');
      },
      changed: () => {},
      completed: bind,
      failed: (error) => errors.push(error),
    });
    try {
      bind(snapshot());
      monitor.receive(input());
      h.flush();
      assert.equal(h.store.getSnapshot('session').sequence, 1);

      await management.manage({ action, expected_revision: 2 });
      assert.deepEqual(errors, ['cua_instance_revision_conflict']);
      assert.equal(h.store.getSnapshot('session'), null);

      bind(snapshot());
      monitor.receive(input({ sequence: 2 }));
      h.flush();
      assert.equal(h.store.getSnapshot('session')?.input_generation, 'generation-a');
      assert.equal(h.store.getSnapshot('session')?.sequence, 2);
    } finally {
      management.dispose();
      monitor.clear();
      h.store.dispose();
    }
  });

  test(`a successful ${action} retires input despite late samples and an active snapshot`, async () => {
    const h = harness();
    const errors = [];
    const sent = [];
    const monitor = new ComputerUseInputMonitor((owner, value) => {
      sent.push(value);
      h.store.receive(value);
    });
    const bind = (value) => {
      monitor.bind(44, { ...scope, credential: 'fixture-only' }, value);
      h.store.updateSnapshot(value);
    };
    const stopped = snapshot([
      session({ stopped: true, presentation: { phase: 'stopped' } }),
    ]);
    stopped.instance = {
      ...stopped.instance,
      installed: action !== 'uninstall',
      enabled: false,
      revision: 4,
    };
    const management = createComputerUseManagement({
      run: async (operation) => {
        h.store.willManage(operation);
        monitor.willManage(operation);
        return stopped;
      },
      changed: () => {},
      completed: bind,
      failed: (error) => errors.push(error),
    });
    try {
      bind(snapshot());
      monitor.receive(input());
      h.flush();
      assert.equal(h.store.getSnapshot('session').sequence, 1);

      await management.manage({ action, expected_revision: 3 });
      assert.deepEqual(errors, []);
      assert.equal(h.store.getSnapshot('session'), null);
      monitor.receive(input({ sequence: 2 }));
      h.flush();
      assert.equal(h.store.getSnapshot('session'), null);

      bind(snapshot());
      monitor.receive(input({ sequence: 2 }));
      h.store.receive(event(input({ sequence: 2 })));
      h.flush();
      assert.equal(h.store.getSnapshot('session'), null);
      assert.equal(sent.filter((value) => value.type === 'computer_use_input').length, 1);
    } finally {
      management.dispose();
      monitor.clear();
      h.store.dispose();
    }
  });
}

test('new activity prevents late refresh results and failures from rolling back the input generation', async () => {
  const h = harness();
  let failures = 0;
  const updates = createComputerUseSnapshotUpdates({
    completed: (value) => h.store.updateSnapshot(value),
    failed: () => {
      failures++;
      h.store.dispose();
    },
  });
  const staleSuccess = updates.refresh();
  const staleFailure = updates.refresh();
  let complete;
  const pending = new Promise((resolve) => {
    complete = resolve;
  });
  const refresh = pending.then((value) => staleSuccess.completed(value));
  updates.activity(snapshot([session({ input_generation: 'generation-b' })]));
  h.store.receive(event(input({ input_generation: 'generation-b' })));
  h.flush();
  complete(snapshot());
  await refresh;
  staleFailure.failed(new Error('old status failed'));
  h.store.receive(event(input({ input_generation: 'generation-b', sequence: 2 })));
  h.flush();
  assert.equal(failures, 0);
  assert.equal(h.store.getSnapshot('session').sequence, 2);
  const beforeStop = updates.refresh();
  updates.activity(snapshot([]));
  beforeStop.completed(snapshot());
  h.store.receive(event(input({ sequence: 10 })));
  h.flush();
  assert.equal(h.store.getSnapshot('session'), null);
  updates.dispose();
});

test('pointer projection uses window points and the contained image, independently of Retina pixels', () => {
  const bounds = computerUseContainedImageBounds(320, 220, 800, 600);
  const point = computerUseCursorPosition(input(), bounds);
  assert.equal(point.x, 160);
  assert.equal(point.y, 110);
  assert.equal(computerUseContainedImageBounds(0, 220, 800, 600), null);
  assert.equal(
    computerUseCursorPosition(
      input({
        virtual_cursor: {
          ...input().virtual_cursor,
          x: -1,
        },
      }),
      bounds,
    ),
    null,
  );
  assert.equal(computerUseInputMatchesPreview(input(), session().presentation), true);
  assert.equal(
    computerUseInputMatchesPreview(input({ target_pid: 43 }), session().presentation),
    false,
  );
  assert.equal(
    computerUseInputMatchesPreview(input(), {
      ...session().presentation,
      preview: { window_id: 'a-stale-window' },
    }),
    false,
  );
  assert.equal(
    computerUseInputMatchesPreview(input(), {
      ...session().presentation,
      phase: 'paused',
    }),
    false,
  );
});

test('held input labels show only mouse buttons and modifier names, not ordinary typed keys', () => {
  assert.deepEqual(
    computerUseHeldLabels(
      input({
        held_keys: [0, 1, 54, 55, 56, 58, 59, 63],
        held_buttons: [0, 2, 4],
      }),
    ),
    [
      'cua.input.button.left',
      'cua.input.button.middle',
      'cua.input.button.additional',
      'cua.input.modifier.command',
      'cua.input.modifier.shift',
      'cua.input.modifier.option',
      'cua.input.modifier.control',
      'cua.input.modifier.fn',
    ],
  );
});

test('the input view distinguishes a dispatch from an observation without showing typed text', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const { ComputerUseInputState } = require(
    `${root}/src/features/settings/ComputerUseWindowPreview.js`,
  );
  const render = (evidence) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ComputerUseInputState, {
          input: input({
            evidence,
            held_keys: [0, 55],
            held_buttons: [0],
            typed_text: 'private fixture text',
          }),
        }),
      ),
    );
  const dispatched = render('dispatched');
  assert.match(dispatched, /Input sent/u);
  assert.match(dispatched, /not yet been confirmed/u);
  assert.match(dispatched, /Left mouse/u);
  assert.match(dispatched, /Command/u);
  assert.doesNotMatch(dispatched, /private fixture text/u);
  assert.match(render('observed'), /Observed in the application/u);
});

test('main forwards only to the bound owner and waits for the snapshot generation', () => {
  const sent = [];
  const monitor = new ComputerUseInputMonitor((owner, event) => sent.push({ owner, event }));
  monitor.receive(input());
  assert.equal(sent.length, 0);
  monitor.clear();
  monitor.bind(44, { ...scope, credential: 'fixture-only' }, snapshot());
  monitor.receive(input({ project_id: 'other' }));
  monitor.receive(input({ session_id: 'unknown' }));
  monitor.receive(input({ run_id: 'other' }));
  assert.equal(sent.length, 0);
  monitor.receive(input());
  monitor.receive(input());
  assert.equal(sent.length, 1);
  assert.equal(sent[0].owner, 44);
  monitor.receive(input({ input_generation: 'generation-b' }));
  assert.equal(sent.length, 1);
  monitor.bind(
    44,
    { ...scope, credential: 'fixture-only' },
    snapshot([session({ input_generation: 'generation-b' })]),
  );
  assert.equal(sent.at(-1).event.input.input_generation, 'generation-b');
  const count = sent.length;
  monitor.receive(input({ sequence: 100 }));
  assert.equal(sent.length, count);
  monitor.willManage({ action: 'stop', session_id: 'session' });
  assert.equal(sent.at(-1).event.type, 'computer_use_input_reset');
  monitor.receive(input({ input_generation: 'generation-b', sequence: 2 }));
  assert.equal(sent.at(-1).event.type, 'computer_use_input_reset');
  monitor.clear(99);
  monitor.bind(
    55,
    { ...scope, project_id: 'second', credential: 'new-fixture' },
    { ...snapshot([]), scope: { tenant_id: 'tenant', project_id: 'second' } },
  );
  assert.equal(sent.at(-1).owner, 44);
  assert.equal(sent.at(-1).event.type, 'computer_use_input_reset');
  monitor.receive(input({ input_generation: 'generation-c' }));
  assert.equal(sent.at(-1).owner, 44);
  monitor.clear();
});

test('mode choice defaults to background and foreground requires an explicit supported selection', () => {
  const React = require('react');
  const jsx = require('react/jsx-runtime');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${root}/src/i18n.js`);
  const { ComputerUseInputModeControl } = require(
    `${root}/src/features/settings/ComputerUseInputModeControl.js`,
  );
  const original = jsx.jsx;
  const selections = [];
  const calls = [];
  jsx.jsx = (type, props, ...args) => {
    if (type === 'select') selections.push(props);
    return original(type, props, ...args);
  };
  const render = (value) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ComputerUseInputModeControl, {
          snapshot: value,
          busy: false,
          manage: async (operation) => calls.push(operation),
        }),
      ),
    );
  try {
    const value = snapshot();
    const html = render(value);
    assert.match(html, /Changing mode stops the current computer-use sessions/u);
    assert.equal(selections.at(-1).value, 'background');
    assert.deepEqual(calls, []);
    selections.at(-1).onChange({ target: { value: 'foreground' } });
    assert.deepEqual(calls, [
      {
        action: 'set_input_mode',
        input_mode: 'foreground',
        expected_revision: 3,
      },
    ]);
    const unavailable = {
      ...value,
      input_support: {
        ...value.input_support,
        background: { supported: false, reason: 'native_backend_unavailable' },
        foreground: { supported: false, reason: 'native_backend_unavailable' },
      },
    };
    assert.match(render(unavailable), /Unavailable for this session/u);
    assert.match(render(unavailable), /native_backend_unavailable/u);
    selections.at(-1).onChange({ target: { value: 'foreground' } });
    assert.equal(calls.length, 1);
  } finally {
    jsx.jsx = original;
  }
});
