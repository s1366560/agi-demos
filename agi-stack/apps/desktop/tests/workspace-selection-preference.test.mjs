import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  readWorkspaceSelectionPreference: read,
  writeWorkspaceSelectionPreference: write,
  workspaceSelectionPreferenceKey: key,
} = require('/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceSelectionPreference.js');
const { resolveRuntimeWorkspaceId } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js',
);

const local = {
  mode: 'local',
  apiBaseUrl: 'http://127.0.0.1:41231',
  tenantId: 'tenant-one',
  projectId: 'project-one',
};
const cloud = { ...local, mode: 'cloud', apiBaseUrl: 'https://api.example.test/api/v1' };

function memoryStorage() {
  const entries = new Map();
  return {
    entries,
    getItem: (name) => entries.get(name) ?? null,
    setItem: (name, value) => entries.set(name, value),
  };
}

test('workspace choice round trips without serializing runtime credentials or configuration', () => {
  const storage = memoryStorage();
  const config = { ...local, apiKey: 'private-key', localApiToken: 'private-token' };
  assert.equal(read(config, 'user-one', storage), null);
  write(config, 'user-one', 'workspace-one', storage);
  assert.equal(read(config, 'user-one', storage), 'workspace-one');
  assert.deepEqual([...storage.entries.values()].map(JSON.parse), [
    { version: 1, workspaceId: 'workspace-one' },
  ]);
  assert.equal(JSON.stringify([...storage.entries]).includes('private-'), false);
});

test('local preference survives the sidecar port changing on restart', () => {
  const storage = memoryStorage();
  write(local, 'user-one', 'workspace-one', storage);
  assert.equal(
    read({ ...local, apiBaseUrl: 'http://127.0.0.1:53002' }, 'user-one', storage),
    'workspace-one',
  );
});

test('restart selection follows the saved workspace, roster lifecycle and unbound conversation', () => {
  const storage = memoryStorage();
  const restarted = { ...local, apiBaseUrl: 'http://127.0.0.1:53002' };
  const archivedTestWorkspace = { id: 'computer-use-qa', is_archived: true };
  const development = { id: 'development' };
  const design = { id: 'design' };
  const operations = { id: 'operations' };
  const visibleSelections = [];
  const restore = (roster, conversation = null) => resolveRuntimeWorkspaceId(
    '',
    restarted.projectId,
    roster,
    conversation,
    read(restarted, 'user-one', storage),
  );

  write(local, 'user-one', development.id, storage);
  visibleSelections.push(restore([archivedTestWorkspace, design, development]));
  visibleSelections.push(restore([design, development, archivedTestWorkspace]));

  const archivedDevelopment = { ...development, status: 'archived' };
  const afterArchive = restore([archivedTestWorkspace, archivedDevelopment, design]);
  visibleSelections.push(afterArchive);
  write(restarted, 'user-one', afterArchive, storage);

  // The saved workspace was removed while the client was closed.
  const afterDeletion = restore([archivedTestWorkspace, archivedDevelopment, operations]);
  visibleSelections.push(afterDeletion);
  write(restarted, 'user-one', afterDeletion, storage);

  visibleSelections.push(restore([operations], {
    project_id: restarted.projectId,
    workspace_id: null,
  }));
  write(restarted, 'user-one', '', storage);
  visibleSelections.push(restore([archivedTestWorkspace, operations]));

  assert.deepEqual(visibleSelections, [
    'development', 'development', 'design', 'operations', '', '',
  ]);
});

test('mode, cloud backend, user, tenant and project each isolate selections', () => {
  const storage = memoryStorage();
  write(cloud, 'user-one', 'workspace-one', storage);
  const scopes = [
    [{ ...cloud, mode: 'local' }, 'user-one'],
    [{ ...cloud, apiBaseUrl: 'https://other.example.test/api/v1' }, 'user-one'],
    [{ ...cloud, apiBaseUrl: 'https://api.example.test/other-api' }, 'user-one'],
    [{ ...cloud, apiBaseUrl: 'http://api.example.test/api/v1' }, 'user-one'],
    [cloud, 'user-two'],
    [{ ...cloud, tenantId: 'tenant-two' }, 'user-one'],
    [{ ...cloud, projectId: 'project-two' }, 'user-one'],
  ];
  for (const [config, user] of scopes) {
    assert.equal(read(config, user, storage), null);
  }
});

test('cloud origin and path are canonical while query and fragment are excluded', () => {
  const storage = memoryStorage();
  write(
    { ...cloud, apiBaseUrl: 'https://API.EXAMPLE.TEST:443/api/./v1/?token=private-query#private-fragment' },
    'user-one',
    'workspace-one',
    storage,
  );
  assert.equal(read(cloud, 'user-one', storage), 'workspace-one');
  assert.equal(decodeURIComponent([...storage.entries.keys()][0]).includes('private-'), false);
});

test('cloud userinfo and invalid backend URLs are rejected without storage writes', () => {
  const storage = memoryStorage();
  for (const apiBaseUrl of [
    'https://user:password@api.example.test/api/v1',
    'https://user@api.example.test/api/v1',
    'file:///private/api',
    'not-a-url',
    '/api/v1',
  ]) {
    const config = { ...cloud, apiBaseUrl };
    write(config, 'user-one', 'workspace-one', storage);
    assert.equal(key(config, 'user-one'), null);
    assert.equal(read(config, 'user-one', storage), null);
  }
  assert.equal(storage.entries.size, 0);
});

test('scope must be authenticated and contain tenant and project identifiers', () => {
  const storage = memoryStorage();
  for (const [config, user] of [
    [local, null],
    [local, undefined],
    [local, '  '],
    [{ ...local, tenantId: '' }, 'user-one'],
    [{ ...local, projectId: ' ' }, 'user-one'],
    [{ ...local, mode: 'unknown' }, 'user-one'],
  ]) {
    write(config, user, 'workspace-one', storage);
    assert.equal(read(config, user, storage), null);
  }
  assert.equal(storage.entries.size, 0);
});

test('an explicit unbound selection is distinct from a missing preference', () => {
  const storage = memoryStorage();
  assert.equal(read(local, 'user-one', storage), null);
  write(local, 'user-one', '', storage);
  assert.equal(read(local, 'user-one', storage), '');
});

test('malformed, unsupported and overbroad stored values do not restore a selection', () => {
  const storage = memoryStorage();
  for (const value of [
    '{',
    'null',
    '[]',
    '"workspace-one"',
    '{}',
    '{"version":2,"workspaceId":"workspace-one"}',
    '{"version":1,"workspaceId":42}',
    '{"version":1,"workspaceId":null}',
    '{"version":1,"workspaceId":" workspace-one "}',
    '{"version":1,"workspaceId":"workspace-one","apiKey":"private-key"}',
  ]) {
    storage.setItem(key(local, 'user-one'), value);
    assert.equal(read(local, 'user-one', storage), null);
  }
});

test('scope identifiers cannot collide through delimiter characters', () => {
  const storage = memoryStorage();
  write({ ...local, tenantId: 'a:b', projectId: 'c' }, 'user-one', 'workspace-one', storage);
  assert.equal(read({ ...local, tenantId: 'a', projectId: 'b:c' }, 'user-one', storage), null);
});

test('denied and full storage never block selection or overwrite the previous choice', () => {
  const storage = memoryStorage();
  write(local, 'user-one', 'workspace-one', storage);
  const fullStorage = { ...storage, setItem() { throw new Error('quota exceeded'); } };
  assert.doesNotThrow(() => write(local, 'user-one', 'workspace-two', fullStorage));
  assert.equal(read(local, 'user-one', storage), 'workspace-one');
  const deniedStorage = { ...storage, getItem() { throw new Error('access denied'); } };
  assert.equal(read(local, 'user-one', deniedStorage), null);
  assert.equal(read(local, 'user-one', null), null);
  assert.doesNotThrow(() => write(local, 'user-one', 'workspace-one', null));
});

test('default storage handles a denied browser getter and a non-browser environment', () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  try {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { get localStorage() { throw new Error('access denied'); } },
    });
    assert.equal(read(local, 'user-one'), null);
    assert.doesNotThrow(() => write(local, 'user-one', 'workspace-one'));
    delete globalThis.window;
    assert.equal(read(local, 'user-one'), null);
    assert.doesNotThrow(() => write(local, 'user-one', 'workspace-one'));
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else delete globalThis.window;
  }
});
