import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const anchor = app.indexOf('const requestId = sessionProjectionRequestRef.current + 1;');
const start = app.lastIndexOf('useEffect(() => {', anchor);
const end = app.indexOf('\n  const sessionProjection =', anchor);
const loader = app
  .slice(start, end)
  .trim()
  .match(/^useEffect\(([\s\S]*), \[([\s\S]*)\]\);$/u);
assert.ok(loader, 'exercise the actual session projection effect and its dependency boundary');
const identityStart = app.indexOf('const scopedConversationId =');
const identityEnd = app.indexOf('\n  const rightPanelScope =', identityStart);
const identitySource = app.slice(identityStart, identityEnd);
assert.ok(identitySource.includes('sessionProjectionConversationIdentity'));

const settle = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

function harness(read) {
  const conversation = {
    id: 'chat-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    workspace_id: 'workspace-1',
  };
  const projection = { conversation, snapshotRevision: 'fixture-revision' };
  let state;
  let display;
  const calls = [];
  const config = {
    mode: 'local',
    apiBaseUrl: 'http://127.0.0.1:40001',
    apiKey: 'fixture-owner',
    localApiToken: 'fixture-launch-a',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
  const context = {
    AbortController,
    config,
    configRef: { current: config },
    desktopRendererGenerationV2: { actions: { read } },
    scopedConversation: conversation,
    scopedConversationId: conversation.id,
    sessionProjectionRefreshRevision: 0,
    sessionProjectionRequestRef: { current: 0 },
    sessionProjectionRevisionRef: { current: null },
    emptySessionProjectionState: { status: 'idle' },
    setSessionProjectionState: (value) => {
      state = value;
    },
    setSessionDisplayProjection: (value) => {
      display = typeof value === 'function' ? value(display) : value;
    },
    signedSessionSnapshotRevision: () => null,
    decodeConversationSessionProjection: (value) => value,
    formatConnectionError: (error) => error.message,
  };
  context.desktopSessionProjectionOperationsV2 = {
    getConversationSession(input) {
      calls.push(input);
      return context.desktopRendererGenerationV2.actions.read(input, projection);
    },
  };
  let dependencies;
  let cleanup;
  let identityDependencies;
  let identity;
  context.useMemo = (factory, next) => {
    if (
      !identityDependencies ||
      !identityDependencies.every((value, index) => Object.is(value, next[index]))
    ) {
      identityDependencies = next;
      identity = factory();
    }
    return identity;
  };
  return {
    context,
    projection,
    calls,
    state: () => state,
    render() {
      context.scopedConversationId = context.scopedConversation?.id ?? '';
      context.sessionProjectionConversationIdentity = runInNewContext(
        `(() => { ${identitySource}; return sessionProjectionConversationIdentity; })()`,
        context
      );
      const next = runInNewContext(`[${loader[2]}]`, context);
      if (dependencies && dependencies.every((value, index) => Object.is(value, next[index])))
        return;
      cleanup?.();
      dependencies = next;
      cleanup = runInNewContext(`(${loader[1]})()`, context);
    },
    close: () => cleanup?.(),
  };
}

test('a selected conversation recovers when its renderer generation becomes available', async () => {
  const ui = harness(() => {
    throw Error('desktop_renderer_service_generation_required');
  });
  try {
    ui.render();
    await settle();
    assert.equal(ui.state().status, 'error');
    ui.context.desktopRendererGenerationV2 = {
      actions: { read: async (_input, projection) => projection },
    };
    ui.render();
    await settle();
    assert.equal(ui.calls.length, 2);
    assert.equal(ui.state().status, 'ready');
  } finally {
    ui.close();
  }
});

test('sidecar endpoint and credentials rotate the projection read without requiring conversation reselection', async () => {
  for (const [key, value] of [
    ['apiBaseUrl', 'http://127.0.0.1:40002'],
    ['apiKey', 'fixture-owner-b'],
    ['localApiToken', 'fixture-launch-b'],
    ['mode', 'cloud'],
    ['tenantId', 'tenant-2'],
    ['projectId', 'project-2'],
    ['workspaceId', 'workspace-2'],
  ]) {
    const ui = harness(async (_input, projection) => projection);
    try {
      ui.render();
      await settle();
      ui.context.config = { ...ui.context.config, [key]: value };
      ui.context.configRef.current = ui.context.config;
      ui.render();
      await settle();
      assert.equal(ui.calls.length, 2, key);
      assert.equal(ui.calls[0].signal.aborted, true, key);
      assert.equal(ui.calls[1].config[key], value, key);
      assert.equal(ui.state().status, 'ready', key);
    } finally {
      ui.close();
    }
  }
});

test('a late response from the retired renderer generation cannot replace the fresh projection', async () => {
  const oldRead = deferred();
  const ui = harness(() => oldRead.promise);
  try {
    ui.render();
    await settle();
    ui.context.desktopRendererGenerationV2 = {
      actions: { read: async (_input, projection) => projection },
    };
    ui.render();
    await settle();
    assert.equal(ui.calls[0].signal.aborted, true);
    assert.equal(ui.state().projection, ui.projection);
    oldRead.resolve({ ...ui.projection, snapshotRevision: 'stale-revision' });
    await settle();
    assert.equal(ui.state().projection, ui.projection);
  } finally {
    ui.close();
  }
});

test('ordinary configuration copies retain the in-flight read', async () => {
  const pending = deferred();
  const ui = harness(() => pending.promise);
  try {
    ui.render();
    await settle();
    ui.context.config = { ...ui.context.config };
    ui.context.configRef.current = ui.context.config;
    ui.render();
    await settle();
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.calls[0].signal.aborted, false);
    pending.resolve(ui.projection);
    await settle();
    assert.equal(ui.state().status, 'ready');
  } finally {
    ui.close();
  }
});

test('same-scope streamed conversation metadata cannot cancel the authority read', async () => {
  const pending = deferred();
  const ui = harness(() => pending.promise);
  try {
    ui.render();
    await settle();
    for (let revision = 1; revision <= 5; revision += 1) {
      ui.context.scopedConversation = {
        ...ui.context.scopedConversation,
        title: `streamed title ${revision}`,
        metadata: { run: { revision } },
      };
      ui.render();
      await settle();
    }
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.calls[0].signal.aborted, false);
    pending.resolve(ui.projection);
    await settle();
    assert.equal(ui.state().status, 'ready');
  } finally {
    ui.close();
  }
});

test('every conversation identity field retires the old authority request', async () => {
  for (const field of ['id', 'tenant_id', 'project_id', 'workspace_id']) {
    const pending = deferred();
    const ui = harness(() => pending.promise);
    try {
      ui.render();
      await settle();
      const value = `changed-${field}`;
      ui.context.scopedConversation = { ...ui.context.scopedConversation, [field]: value };
      ui.render();
      await settle();
      assert.equal(ui.calls.length, 2, field);
      assert.equal(ui.calls[0].signal.aborted, true, field);
      assert.equal(ui.calls[1].conversation[field], value, field);
    } finally {
      ui.close();
    }
  }
});

test('an invalidation burst admits only the latest response and can settle', async () => {
  const reads = [];
  const ui = harness(() => {
    const pending = deferred();
    reads.push(pending);
    return pending.promise;
  });
  try {
    ui.render();
    await settle();
    for (let revision = 1; revision <= 3; revision += 1) {
      ui.context.sessionProjectionRefreshRevision = revision;
      ui.render();
      await settle();
    }
    assert.equal(reads.length, 4);
    for (const call of ui.calls.slice(0, -1)) assert.equal(call.signal.aborted, true);
    reads.at(-1).resolve(ui.projection);
    await settle();
    assert.equal(ui.state().status, 'ready');
    for (const read of reads.slice(0, -1)) read.resolve({ stale: true });
    await settle();
    assert.equal(ui.state().projection, ui.projection);
  } finally {
    ui.close();
  }
});
