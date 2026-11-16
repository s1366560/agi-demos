import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  entryPoints: [
    new URL('../src/features/chat/permissionAutoApprovalHistory.ts', import.meta.url).pathname,
  ],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'cjs',
});
const module = { exports: {} };
new Function('module', 'exports', compiled.outputFiles[0].text)(module, module.exports);
const {
  permissionAutoApprovalScope,
  hideConfirmedAutoApprovedPermissions,
  readPermissionAutoApprovalHistory,
  recordSuccessfulPermissionAutoApproval,
  PERMISSION_AUTO_APPROVAL_STORAGE_PREFIX,
  MAX_PERMISSION_AUTO_APPROVAL_HISTORY,
} = module.exports;

const config = {
  mode: 'cloud',
  apiBaseUrl: 'https://api.example.test/api/v1',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  apiKey: 'must-not-be-stored',
  localApiToken: 'must-not-be-stored-either',
};
function memoryStorage() {
  const values = new Map();
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test('successful auto-approval provenance survives reload without storing credentials or request content', () => {
  const storage = memoryStorage();
  const scope = permissionAutoApprovalScope(config, 'conversation-1');
  assert.deepEqual(readPermissionAutoApprovalHistory(scope, storage), []);
  assert.deepEqual(recordSuccessfulPermissionAutoApproval(scope, 'request-1', 'full', storage), [
    { requestId: 'request-1', preset: 'full' },
  ]);
  assert.deepEqual(readPermissionAutoApprovalHistory(scope, storage), [
    { requestId: 'request-1', preset: 'full' },
  ]);
  assert.equal(storage.values.size, 1);
  const [[key, value]] = [...storage.values];
  assert.ok(!key.includes(config.apiKey));
  assert.ok(!key.includes(config.localApiToken));
  assert.deepEqual(JSON.parse(value), [{ requestId: 'request-1', preset: 'full' }]);
});

test('history scopes isolate every runtime/server/account/project/workspace/conversation dimension', () => {
  const storage = memoryStorage();
  const scope = permissionAutoApprovalScope(config, 'conversation-1');
  recordSuccessfulPermissionAutoApproval(scope, 'request-1', 'relaxed', storage);
  for (const changed of [
    { mode: 'local' },
    { apiBaseUrl: 'https://other.example.test/api/v1' },
    { apiBaseUrl: 'https://api.example.test/other' },
    { tenantId: 'tenant-2' },
    { projectId: 'project-2' },
    { workspaceId: 'workspace-1' },
  ]) {
    assert.deepEqual(
      readPermissionAutoApprovalHistory(
        permissionAutoApprovalScope({ ...config, ...changed }, 'conversation-1'),
        storage,
      ),
      [],
    );
  }
  assert.deepEqual(
    readPermissionAutoApprovalHistory(
      permissionAutoApprovalScope(config, 'conversation-2'),
      storage,
    ),
    [],
  );
  assert.equal(
    permissionAutoApprovalScope(
      { ...config, apiBaseUrl: `${config.apiBaseUrl}/` },
      'conversation-1',
    ),
    scope,
  );
});

test('missing identity or credential-bearing URLs cannot produce a storage scope', () => {
  for (const changed of [
    { tenantId: '' },
    { projectId: ' ' },
    { mode: 'invalid' },
    { apiBaseUrl: 'invalid' },
    { apiBaseUrl: 'file:///tmp/server' },
    { apiBaseUrl: 'https://user:password@api.example.test' },
    { apiBaseUrl: 'https://api.example.test?token=secret' },
    { apiBaseUrl: 'https://api.example.test#secret' },
  ])
    assert.equal(permissionAutoApprovalScope({ ...config, ...changed }, 'conversation-1'), null);
  assert.equal(permissionAutoApprovalScope(config, ' '), null);
});

test('only explicit successful auto presets enter history and repeated IDs remain unique', () => {
  const storage = memoryStorage();
  const scope = permissionAutoApprovalScope(config, 'conversation-1');
  recordSuccessfulPermissionAutoApproval(scope, 'request-1', 'default', storage);
  recordSuccessfulPermissionAutoApproval(scope, ' ', 'full', storage);
  assert.equal(storage.values.size, 0);
  recordSuccessfulPermissionAutoApproval(scope, 'request-1', 'relaxed', storage);
  recordSuccessfulPermissionAutoApproval(scope, 'request-1', 'full', storage);
  assert.deepEqual(readPermissionAutoApprovalHistory(scope, storage), [
    { requestId: 'request-1', preset: 'full' },
  ]);
});

test('history evicts oldest entries at a fixed structural bound', () => {
  const storage = memoryStorage();
  const scope = permissionAutoApprovalScope(config, 'conversation-1');
  for (let index = 0; index < MAX_PERMISSION_AUTO_APPROVAL_HISTORY + 2; index += 1) {
    recordSuccessfulPermissionAutoApproval(scope, `request-${index}`, 'full', storage);
  }
  const entries = readPermissionAutoApprovalHistory(scope, storage);
  assert.equal(entries.length, MAX_PERMISSION_AUTO_APPROVAL_HISTORY);
  assert.equal(entries[0].requestId, 'request-2');
  recordSuccessfulPermissionAutoApproval(scope, 'request-2', 'relaxed', storage);
  const refreshed = readPermissionAutoApprovalHistory(scope, storage);
  assert.equal(refreshed.at(-1).requestId, 'request-2');
  assert.equal(refreshed.length, MAX_PERMISSION_AUTO_APPROVAL_HISTORY);
});

test('malformed storage is ignored and extra fields are never persisted', () => {
  const storage = memoryStorage();
  const scope = permissionAutoApprovalScope(config, 'conversation-1');
  const key = `${PERMISSION_AUTO_APPROVAL_STORAGE_PREFIX}:${scope}`;
  for (const raw of ['broken', '{}', 'null', '[null,{}, {"requestId":1,"preset":"full"}]']) {
    storage.setItem(key, raw);
    assert.deepEqual(readPermissionAutoApprovalHistory(scope, storage), []);
  }
  storage.setItem(
    key,
    JSON.stringify([{ requestId: 'request-1', preset: 'full', content: 'must not persist' }]),
  );
  recordSuccessfulPermissionAutoApproval(scope, 'request-2', 'relaxed', storage);
  assert.deepEqual(JSON.parse(storage.values.get(key)), [
    { requestId: 'request-1', preset: 'full' },
    { requestId: 'request-2', preset: 'relaxed' },
  ]);
});

test('disabled, denied or full storage cannot throw or invent persisted provenance', () => {
  const throwing = {
    getItem() {
      throw new Error('denied');
    },
    setItem() {
      throw new Error('full');
    },
  };
  assert.deepEqual(readPermissionAutoApprovalHistory('scope', throwing), []);
  assert.deepEqual(recordSuccessfulPermissionAutoApproval('scope', 'request-1', 'full', throwing), [
    { requestId: 'request-1', preset: 'full' },
  ]);
  assert.deepEqual(recordSuccessfulPermissionAutoApproval(null, 'request-1', 'full', throwing), []);
  assert.deepEqual(readPermissionAutoApprovalHistory('scope', null), []);
});

function timelineItem(id, type, overrides = {}) {
  return { id, type, eventTimeUs: 1, eventCounter: 0, ...overrides };
}

test('display folds authoritative replies before hiding explicitly automatic grants', () => {
  const items = [
    timelineItem('auto', 'permission_asked', { requestId: 'automatic' }),
    timelineItem('reply', 'permission_replied', {
      data: {
        request_id: 'automatic',
        granted: true,
        auto_approved: true,
        preset: 'full',
      },
    }),
    timelineItem('manual', 'permission_asked', { requestId: 'manual' }),
    timelineItem('manual-reply', 'permission_replied', {
      data: {
        request_id: 'manual',
        granted: true,
      },
    }),
  ];
  const original = structuredClone(items);
  const displayed = hideConfirmedAutoApprovedPermissions(items, []);
  assert.deepEqual(
    displayed.map((item) => item.id),
    ['manual'],
  );
  assert.equal(displayed[0].answered, true);
  assert.equal(displayed[0].granted, true);
  assert.deepEqual(items, original);
});

test('exact persisted provenance hides only matching resolved granted permission requests', () => {
  const history = [{ requestId: 'recorded', preset: 'full' }];
  const items = [
    timelineItem('auto', 'permission_asked', {
      requestId: 'recorded',
      answered: true,
      granted: true,
    }),
    timelineItem('manual', 'permission_asked', {
      requestId: 'manual',
      answered: true,
      granted: true,
    }),
    timelineItem('pending', 'permission_asked', { requestId: 'recorded', answered: false }),
    timelineItem('denied', 'permission_asked', {
      requestId: 'recorded',
      answered: true,
      granted: false,
    }),
    timelineItem('unknown', 'permission_asked', { requestId: 'recorded', answered: true }),
    timelineItem('question', 'clarification_asked', {
      requestId: 'recorded',
      answered: true,
      granted: true,
    }),
  ];
  assert.deepEqual(
    hideConfirmedAutoApprovedPermissions(items, history).map((item) => item.id),
    ['manual', 'pending', 'denied', 'unknown', 'question'],
  );
  assert.deepEqual(
    hideConfirmedAutoApprovedPermissions(items, []).map((item) => item.id),
    ['auto', 'manual', 'pending', 'denied', 'unknown', 'question'],
  );
});

test('automatic markers cannot hide pending or denied cards', () => {
  const items = [
    timelineItem('pending', 'permission_asked', { requestId: 'p', autoApprovalPreset: 'full' }),
    timelineItem('denied', 'permission_asked', {
      requestId: 'd',
      answered: true,
      granted: false,
      autoApprovalPreset: 'full',
    }),
    timelineItem('relaxed', 'permission_asked', {
      requestId: 'a',
      answered: true,
      granted: true,
      autoApprovalPreset: 'relaxed',
    }),
  ];
  assert.deepEqual(
    hideConfirmedAutoApprovedPermissions(items, []).map((item) => item.id),
    ['pending', 'denied'],
  );
});

test('only caller-validated in-flight auto requests suppress pending cards while denial remains visible', () => {
  const items = [
    timelineItem('automatic', 'permission_asked', { requestId: 'pending-auto', answered: false }),
    timelineItem('manual', 'permission_asked', { requestId: 'pending-manual', answered: false }),
    timelineItem('denied', 'permission_asked', {
      requestId: 'denied',
      answered: true,
      granted: false,
    }),
    timelineItem('denied-pending', 'permission_asked', {
      requestId: 'denied-pending',
      answered: false,
      granted: false,
    }),
    timelineItem('clarification', 'clarification_asked', {
      requestId: 'pending-auto',
      answered: false,
    }),
  ];
  const pending = new Set(['pending-auto', 'denied', 'denied-pending']);
  assert.deepEqual(
    hideConfirmedAutoApprovedPermissions(items, [], pending).map((item) => item.id),
    ['manual', 'denied', 'denied-pending', 'clarification'],
  );
});

test('removing a failed automatic submission restores its pending manual fallback without persisting provenance', () => {
  const items = [
    timelineItem('automatic', 'permission_asked', {
      payload: { request_id: 'request-auto' },
      answered: false,
    }),
  ];
  const original = structuredClone(items);
  const history = [];
  const pending = new Set(['request-auto']);
  assert.deepEqual(hideConfirmedAutoApprovedPermissions(items, history, pending), []);
  pending.delete('request-auto');
  assert.deepEqual(hideConfirmedAutoApprovedPermissions(items, history, pending), items);
  assert.deepEqual(hideConfirmedAutoApprovedPermissions(items, history), items);
  assert.deepEqual(history, []);
  assert.deepEqual(items, original);
});


test('cross-client persisted automatic replies hide without local history while manual and denied remain', () => {
  const items = [
    timelineItem('web-auto', 'permission_asked', {requestId:'web-auto'}),
    timelineItem('web-reply', 'permission_replied', {requestId:'web-auto',granted:true,auto_approved:true,preset:'full'}),
    timelineItem('manual', 'permission_asked', {requestId:'manual'}),
    timelineItem('manual-reply', 'permission_replied', {requestId:'manual',granted:true}),
    timelineItem('denied', 'permission_asked', {requestId:'denied'}),
    timelineItem('denied-reply', 'permission_replied', {requestId:'denied',granted:false,auto_approved:true,preset:'full'}),
  ];
  assert.deepEqual(hideConfirmedAutoApprovedPermissions(items, []).map(item=>item.id), ['manual','denied']);
});
