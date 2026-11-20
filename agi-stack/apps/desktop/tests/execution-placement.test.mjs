import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const {
  ComposerExecutionPlacement,
} = require(`${root}/features/chat/ComposerExecutionPlacement.js`);
const {
  EXECUTION_PLACEMENT_STORAGE_KEY,
  LOCAL_EXECUTION_PROTOCOL_AVAILABLE,
  cloudExecutionWire,
  decideDirectoryConfig,
  decideExecutionSend,
  decideExecutionSwitch,
  defaultExecutionPlacementPreference,
  executionPlacementScope,
  inheritableExecutionRun,
  localPathMatchesRun,
  localRootBasename,
  messagePermissionMode,
  readExecutionPlacementPreference,
  resolveComposerPlacement,
  webOffersLocalTarget,
  wireContainsAbsolutePath,
  writeExecutionPlacementPreference,
} = require(`${root}/features/chat/executionPlacementModel.js`);

const absoluteRoot = '/Users/alice/src/agi-demos';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

const render = (element) =>
  renderToStaticMarkup(React.createElement(I18nProvider, null, element));

test('new desktop placement defaults to this computer and keeps full access broad', () => {
  assert.equal(LOCAL_EXECUTION_PROTOCOL_AVAILABLE, false);
  assert.deepEqual(defaultExecutionPlacementPreference(), {
    target: 'local',
    localRoot: null,
  });
  assert.equal(messagePermissionMode('full'), 'full_access');
  assert.equal(messagePermissionMode('full', true), null);
  assert.equal(messagePermissionMode('relaxed'), 'automatic');
  assert.equal(messagePermissionMode('default'), null);
  assert.notEqual(messagePermissionMode('full'), 'ask');
  assert.notEqual(messagePermissionMode('full'), 'automatic');
  assert.notEqual(messagePermissionMode('full'), 'read_only');
  assert.notEqual(messagePermissionMode('full'), 'workspace_write');
});

test('placement preferences are isolated by user and project and never publish an absolute path', () => {
  const storage = memoryStorage();
  const alice = executionPlacementScope('alice', 'project-a');
  const bob = executionPlacementScope('bob', 'project-a');
  const otherProject = executionPlacementScope('alice', 'project-b');
  writeExecutionPlacementPreference(
    alice,
    { target: 'local', localRoot: absoluteRoot },
    storage,
    'machine-a',
  );
  writeExecutionPlacementPreference(
    bob,
    { target: 'cloud', localRoot: null },
    storage,
    'machine-a',
  );
  assert.deepEqual(readExecutionPlacementPreference(alice, storage), {
    target: 'local',
    localRoot: absoluteRoot,
  });
  assert.equal(readExecutionPlacementPreference(bob, storage).target, 'cloud');
  assert.equal(readExecutionPlacementPreference(otherProject, storage).target, 'local');
  assert.equal(readExecutionPlacementPreference(otherProject, storage).localRoot, null);
  const stored = storage.getItem(EXECUTION_PLACEMENT_STORAGE_KEY);
  assert.match(stored, /agi-demos/);
  const wire = cloudExecutionWire();
  assert.equal(wireContainsAbsolutePath(wire, [absoluteRoot]), false);
  assert.equal(localRootBasename(absoluteRoot), 'agi-demos');
  assert.equal(localRootBasename('C:\\Users\\alice\\src\\agi-demos'), 'agi-demos');
  assert.equal(wire.local_root_label, null);
});

test('continuing a session inherits the newest non-cancelled run and rejects another machine path', () => {
  const runs = [
    {
      status: 'cancelled',
      execution_target: 'cloud',
      updated_at: '2026-11-20T03:00:00Z',
    },
    {
      status: 'completed',
      execution_target: 'local',
      execution_machine_id: 'machine-b',
      local_root_label: 'agi-demos',
      updated_at: '2026-11-20T02:00:00Z',
    },
    {
      status: 'completed',
      execution_target: 'cloud',
      updated_at: '2026-11-20T01:00:00Z',
    },
  ];
  assert.equal(inheritableExecutionRun(runs)?.execution_machine_id, 'machine-b');
  const placement = resolveComposerPlacement({
    surface: 'desktop',
    preference: { target: 'cloud', localRoot: null },
    configuredRoot: absoluteRoot,
    runs,
    active: false,
    localMachineId: 'machine-a',
    sessionOverride: null,
  });
  assert.equal(placement.source, 'run');
  assert.equal(placement.target, 'local');
  assert.equal(placement.pathUnavailable, true);
  assert.equal(
    localPathMatchesRun({
      configuredRoot: absoluteRoot,
      label: 'agi-demos',
      runMachineId: 'machine-a',
      localMachineId: 'machine-a',
    }),
    true,
  );
  const decision = decideExecutionSend({ surface: 'desktop', placement });
  assert.equal(decision.ok, false);
  assert.equal(decision.code, 'LOCAL_ROOT_UNAVAILABLE');
  assert.equal('wire' in decision, false);
});

test('local send is an explicit unsupported error and cloud send cannot carry the absolute path', () => {
  const placement = resolveComposerPlacement({
    surface: 'desktop',
    preference: { target: 'local', localRoot: absoluteRoot },
    configuredRoot: absoluteRoot,
    runs: [],
    active: false,
    localMachineId: 'machine-a',
    sessionOverride: null,
  });
  const blocked = decideExecutionSend({
    surface: 'desktop',
    placement,
  });
  assert.equal(blocked.ok, false);
  assert.equal(blocked.code, 'LOCAL_EXECUTION_UNAVAILABLE');
  const cloud = decideExecutionSend({
    surface: 'desktop',
    placement: { ...placement, target: 'cloud', localRootLabel: null, pathUnavailable: false },
  });
  assert.equal(cloud.ok, true);
  assert.equal(cloud.wire.execution_target, 'cloud');
  assert.equal(cloud.permissionMode, null);
  assert.equal(messagePermissionMode('full'), 'full_access');
  assert.equal(wireContainsAbsolutePath(cloud.wire, [absoluteRoot, 'alice']), false);
  assert.equal(decideExecutionSwitch(true).ok, false);
  assert.equal(decideExecutionSwitch(false).ok, true);
  assert.equal(
    decideDirectoryConfig({
      previous: { target: 'local', localRoot: absoluteRoot },
      selectedPath: null,
      failed: true,
    }).ok,
    false,
  );
});

test('web composer does not offer this computer and a local run is read-only', () => {
  assert.equal(webOffersLocalTarget(), false);
  const placement = resolveComposerPlacement({
    surface: 'web',
    preference: { target: 'local', localRoot: absoluteRoot },
    configuredRoot: absoluteRoot,
    runs: [
      {
        status: 'completed',
        execution_target: 'local',
        local_root_label: 'agi-demos',
        updated_at: '2026-11-20T02:00:00Z',
      },
    ],
    active: false,
    localMachineId: null,
    sessionOverride: null,
  });
  assert.equal(placement.target, 'local');
  assert.equal(placement.readOnly, true);
  const decision = decideExecutionSend({ surface: 'web', placement });
  assert.equal(decision.ok, false);
  assert.equal(decision.code, 'WEB_LOCAL_RUN_READONLY');
});

test('the placement bar sits above the editor for both composer variants and drops the footer runtime target', () => {
  const html = render(
    React.createElement(ComposerExecutionPlacement, {
      variant: 'session',
      target: 'local',
      localRootLabel: 'agi-demos',
      readOnly: true,
      pathUnavailable: false,
      notice: 'Local execution is not available yet.',
      onTargetChange: () => undefined,
      onPickDirectory: () => undefined,
      onManageEnvironment: () => undefined,
    }),
  );
  assert.match(html, /data-variant="session"/);
  assert.match(html, /data-readonly="true"/);
  assert.match(html, /This computer|此计算机/);
  assert.match(html, /agi-demos/);
  assert.equal(html.includes(absoluteRoot), false);
  const workspace = render(
    React.createElement(ComposerExecutionPlacement, {
      variant: 'workspace',
      target: 'cloud',
      localRootLabel: null,
      readOnly: false,
      pathUnavailable: false,
      notice: null,
      onTargetChange: () => undefined,
      onPickDirectory: () => undefined,
      onManageEnvironment: () => undefined,
    }),
  );
  assert.match(workspace, /data-variant="workspace"/);
  assert.match(workspace, /Cloud|云端/);
  assert.match(workspace, /Default environment|默认环境/);
  assert.match(workspace, /Create environment|创建环境/);
  assert.match(workspace, /disabled/);
  const chatPanel = readFileSync(
    new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
    'utf8',
  );
  const bar = chatPanel.indexOf('<ComposerExecutionPlacement');
  const editor = chatPanel.indexOf('session-composer-editor');
  assert.ok(bar > 0 && editor > bar);
  assert.equal(chatPanel.includes('onRuntimeTargetChange'), false);
  assert.equal(chatPanel.includes('runtimeTargetLabel'), false);
  assert.match(
    chatPanel,
    /showRuntimeControls &&[\s\S]*?<ComposerControls[\s\S]*?onModelChange=\{onModelChange\}/,
  );
});
