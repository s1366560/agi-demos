import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { setImmediate } from 'node:timers/promises';
import {
  memory,
  nativeScope,
  projectScope,
  cases,
  envelope,
  status,
  pullContext,
  outcome,
} from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const dist = process.env.I5_DIAGNOSTICS_DIST ?? '/tmp/agistack-project-knowledge-test-dist';
const { createNativeMemoriesRouteControllers } = require(
  `${dist}/src/features/project-knowledge/nativeMemoriesRouteControllers.js`,
);
const { NativeMemoriesRouteSurface } = require(
  `${dist}/src/features/project-knowledge/NativeMemoriesRouteSurface.js`,
);
const { NativeMemoriesRouteContextProvider } = require(
  `${dist}/src/features/project-knowledge/NativeMemoriesRouteContext.js`,
);
const { I18nProvider } = require(`${dist}/src/i18n.js`);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const configuration = {
  revision: 1,
  build_id: 'build',
  provider_id: 'provider',
  provider_revision: 0,
  model_id: 'embedding',
  dimensions: 2,
  input_contract_version: 1,
  normalization_version: 1,
};
const authority = {
  scope: projectScope,
  userId: 'local-actor',
  sessionId: 'session',
  contextRevision: nativeScope.context_revision,
  generationDigest: nativeScope.digest,
  available: true,
  allowedActions: [
    'view',
    'list',
    'get',
    'update',
    'configuration',
    'entities',
    'failed_processing',
    'failed_index',
    'processing_audits',
    'retry_index',
    'sync_status',
    'sync_pull',
    'pull_conflict_context',
    'resolve_pull',
  ],
};
const sourceFor = (value) => ({
  tenant_id: projectScope.tenantId,
  project_id: projectScope.projectId,
  memory_id: value.id,
  revision: value.version,
  change_sequence: value.version,
});
function fixture(options = {}) {
  const calls = [];
  const state = { memory: structuredClone(memory), applied: 1, pending: 0 };
  const failItem = () => ({
    input: { source: sourceFor(state.memory), audit_attempt: 1, input_digest: 'ab'.repeat(32) },
    attempt: 2,
    failure: 'provider_unavailable',
  });
  const client = {
    observeScope: async () => nativeScope,
    execute: async (scope, command, request) => {
      calls.push({ kind: 'storage', scope, command, request });
      if (options.execute) {
        const response = await options.execute(command);
        if (response) return response;
      }
      let result;
      if (command.operation === 'get') result = { memory: structuredClone(state.memory) };
      else if (command.operation === 'sync_status')
        result = { status: { ...status, pending_changes: state.pending } };
      else if (command.operation === 'pull_conflict_context')
        result = { context: { ...pullContext, local: structuredClone(state.memory) } };
      else if (command.operation === 'update') {
        state.memory = { ...command.memory, version: command.expected_revision + 1 };
        state.applied = 0;
        state.pending = 1;
        result = {
          receipt: {
            sequence: state.memory.version,
            memory: structuredClone(state.memory),
            deleted: false,
          },
          replayed: false,
          processing_status: 'accepted',
        };
      } else if (command.operation === 'sync_pull' || command.operation === 'resolve_pull') {
        state.memory = {
          ...state.memory,
          content: 'new source version',
          version: state.memory.version + 1,
        };
        state.applied = 0;
        result =
          command.operation === 'resolve_pull'
            ? outcome
            : { next_cursor: 3, applied: 1, conflicts: 0, has_more: false };
      } else result = structuredClone(cases.find(([q]) => q.operation === command.operation)?.[1]);
      return envelope(command, result);
    },
  };
  const processingClient = {
    query: async (scope, command, request) => {
      calls.push({ kind: 'processing', scope, command, request });
      const result =
        command.operation === 'configuration'
          ? {
              configuration,
              active_build_id: null,
              processing: {
                current_sources: 1,
                applied_sources: state.applied,
                pending_sources: 1 - state.applied,
                failed_sources: 0,
              },
              index: {
                current_sources: state.applied,
                completed_sources: 0,
                failed_sources: state.applied,
              },
            }
          : command.operation === 'entities'
            ? {
                items: state.applied
                  ? [
                      {
                        reference: { source: sourceFor(state.memory), entity_index: 0 },
                        audit_attempt: 1,
                        entity: { name: 'entity', kind: 'topic' },
                      },
                    ]
                  : [],
                next_cursor: null,
              }
            : {
                items: command.operation === 'failed_index' && state.applied ? [failItem()] : [],
                next_cursor: null,
              };
      return { contract_version: '1.0.0', scope: nativeScope, result: structuredClone(result) };
    },
  };
  const connection = {
    connection_revision: 'revision',
    authority: 'https://fixture.invalid',
    actor_id: status.link.remote_actor_id,
  };
  const enrollment = {
    enabled: true,
    can_enroll: false,
    generation: {
      contract_version: '1.0.0',
      descriptor: { profile_id: 'cloud', generation: 1, digest: 'digest' },
    },
  };
  const binding = {
    authority: { ...authority, ...options.authority },
    client,
    processingClient,
    listClient: {
      load: async (scope) => {
        calls.push({ kind: 'list' });
        return {
          scope,
          scopeRevision: 7,
          authority: 'local',
          availability: 'available',
          reasonCode: null,
          allowedActions: ['view'],
          memories: [],
          page: 1,
          pageSize: 50,
          total: 0,
        };
      },
    },
    processingCommandClient: {
      execute: async (scope, command, request) => {
        calls.push({ kind: 'write', scope, command, request });
        return {
          contract_version: '1.0.0',
          scope: nativeScope,
          result: { accepted: true, input: command.input, attempt: command.expected_attempt },
        };
      },
    },
    connectionClient: {
      execute: async (scope, command) => ({
        contract_version: '1.0.0',
        scope: nativeScope,
        result:
          command.operation === 'connection'
            ? { connection }
            : command.operation === 'tenants'
              ? { connection, items: [{ id: 'tenant', name: 'Remote tenant' }] }
              : command.operation === 'projects'
                ? {
                    connection,
                    items: [{ id: 'project', tenant_id: 'tenant', name: 'Remote project' }],
                  }
                : { connection, enrollment, association_state: 'verified' },
      }),
    },
  };
  const controllers = createNativeMemoriesRouteControllers(binding);
  const ready = async () => {
    await controllers.connection.refresh();
    await controllers.connection.selectTenant('tenant');
    await controllers.connection.selectProject('project');
    await controllers.connection.bind();
    await setImmediate();
    await controllers.retrieval.refreshConfiguration();
    controllers.retrieval.setMode('entities');
    await controllers.retrieval.submit();
    await controllers.retrieval.viewSource(sourceFor(state.memory));
    await controllers.diagnostics.refresh('failed_index');
    await controllers.processing.selectDiagnosticFailure(controllers.diagnostics.selection(0));
    await controllers.processing.review('retry_index');
    assert.equal(controllers.processing.getSnapshot().phase, 'reviewing');
    assert.equal(controllers.retrieval.getSnapshot().source.version, 1);
  };
  return { binding, controllers, calls, state, ready };
}
function assertRefreshed(f) {
  assert.equal(f.controllers.retrieval.getSnapshot().configuration.processing.applied_sources, 0);
  assert.equal(f.controllers.retrieval.getSnapshot().configuration.processing.pending_sources, 1);
  assert.equal(f.controllers.retrieval.getSnapshot().result, null);
  assert.equal(f.controllers.retrieval.getSnapshot().source, null);
  assert.equal(f.controllers.retrieval.getSnapshot().navigation, null);
  assert.equal(f.controllers.processing.getSnapshot().failedTask, null);
  assert.equal(f.controllers.processing.getSnapshot().selection, null);
  assert.equal(f.controllers.processing.getSnapshot().snapshot.processing.applied_sources, 0);
  assert.equal(f.controllers.diagnostics.getSnapshot().index.items.length, 0);
  assert.equal(f.calls.filter((call) => call.kind === 'write').length, 0);
  assert(f.calls.some((call) => call.kind === 'list'));
  for (const call of f.calls.filter((call) => call.kind === 'processing'))
    assert.deepEqual(call.scope, projectScope);
}

test('actual local Surface mounts diagnostics and existing retry control from one admitted binding', () => {
  const f = fixture();
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        NativeMemoriesRouteContextProvider,
        { value: f.binding },
        React.createElement(NativeMemoriesRouteSurface, {
          context: { tenantId: 'tenant-1', projectId: 'project-1' },
        }),
      ),
    ),
  );
  assert.match(html, /Processing diagnostics/);
  assert.match(html, /Extraction failures/);
  assert.match(html, /Selected build index failures/);
  assert.match(html, /Review failed indexing task retry/);
  const denied = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        NativeMemoriesRouteContextProvider,
        { value: { ...f.binding, authority: { ...authority, available: false } } },
        React.createElement(NativeMemoriesRouteSurface, {
          context: { tenantId: 'tenant-1', projectId: 'project-1' },
        }),
      ),
    ),
  );
  assert.doesNotMatch(denied, /Processing diagnostics/);
});

test('accepted sync pull refreshes processing coverage and clears stale retrieval, source and failed job selection', async () => {
  const f = fixture();
  await f.ready();
  await f.controllers.sync.sync('sync_pull');
  await setImmediate();
  assert.equal(f.state.memory.version, 2);
  assertRefreshed(f);
  assert.equal(f.calls.filter((call) => call.command?.operation === 'sync_pull').length, 1);
});

test('accepted local edit refreshes pending sync changes and every derived read model', async () => {
  const f = fixture();
  await f.ready();
  assert.equal(f.controllers.sync.getSnapshot().status.pending_changes, 0);
  await f.controllers.editor.open(memory.id, 'edit');
  f.controllers.editor.setDraft({ content: 'edited local source' });
  await f.controllers.editor.save();
  await setImmediate();
  assert.equal(f.controllers.editor.getSnapshot().notice, 'accepted');
  assert.equal(f.controllers.sync.getSnapshot().status.pending_changes, 1);
  assertRefreshed(f);
});

test('accepted conflict resolution refreshes current coverage and removes stale source navigation', async () => {
  const f = fixture();
  await f.ready();
  await f.controllers.conflicts.open({ kind: 'pull', id: memory.id });
  f.controllers.conflicts.choose('use_remote');
  await f.controllers.conflicts.submit();
  await setImmediate();
  assert.equal(f.controllers.conflicts.getSnapshot().phase, 'accepted');
  assertRefreshed(f);
});

test('late editor receipt after binding retirement cannot refresh models or restore diagnostic rows', async () => {
  let release;
  const f = fixture({
    execute: (command) =>
      command.operation === 'update'
        ? new Promise((resolve) => {
            release = resolve;
          })
        : null,
  });
  await f.ready();
  await f.controllers.editor.open(memory.id, 'edit');
  f.controllers.editor.setDraft({ content: 'edited' });
  const pending = f.controllers.editor.save();
  for (const controller of Object.values(f.controllers)) controller.stop();
  const before = f.calls.length;
  release(
    envelope(
      { operation: 'update' },
      {
        receipt: { sequence: 2, memory: { ...memory, version: 2 }, deleted: false },
        replayed: false,
        processing_status: 'accepted',
      },
    ),
  );
  await pending;
  await setImmediate();
  assert.equal(f.calls.length, before);
  assert.equal(f.controllers.diagnostics.getSnapshot().index, null);
});

test('accepted edit cancels an older sync status read before it can restore the stale pending count', async () => {
  let hold = false;
  let release;
  const f = fixture({
    execute: (command) => {
      if (hold && command.operation === 'sync_status') {
        hold = false;
        return new Promise((resolve) => {
          release = resolve;
        });
      }
      return null;
    },
  });
  await f.ready();
  hold = true;
  const previous = f.controllers.sync.refresh();
  await setImmediate();
  await f.controllers.editor.open(memory.id, 'edit');
  f.controllers.editor.setDraft({ content: 'source changes while status is pending' });
  await f.controllers.editor.save();
  await setImmediate();
  assert.equal(f.controllers.sync.getSnapshot().status.pending_changes, 1);
  release(envelope({ operation: 'sync_status' }, { status: { ...status, pending_changes: 0 } }));
  await previous;
  assert.equal(f.controllers.sync.getSnapshot().status.pending_changes, 1);
  assertRefreshed(f);
});

test('an acknowledged pull invalidates derived readers even if its follow-up sync status read fails', async () => {
  let failStatus = false;
  const f = fixture({
    execute: (command) => {
      if (command.operation === 'sync_pull') failStatus = true;
      if (failStatus && command.operation === 'sync_status')
        throw Object.assign(Error('read failed'), { status: 503 });
      return null;
    },
  });
  await f.ready();
  await f.controllers.sync.sync('sync_pull');
  await setImmediate();
  assert.equal(f.controllers.sync.getSnapshot().phase, 'error');
  assert.equal(f.controllers.sync.getSnapshot().recoveryRequired, false);
  assert.equal(f.controllers.sync.getSnapshot().result.applied, 1);
  assertRefreshed(f);
});

test('an unknown sync write preserves its recovery barrier and never publishes an accepted source refresh', async () => {
  const f = fixture({
    execute: (command) => {
      if (command.operation === 'sync_pull')
        throw Object.assign(Error('response lost'), { status: 503 });
      return null;
    },
  });
  await f.ready();
  await f.controllers.sync.sync('sync_pull');
  await setImmediate();
  assert.equal(f.controllers.sync.getSnapshot().recoveryRequired, true);
  const snapshot = f.controllers.sync.getSnapshot();
  f.controllers.sync.invalidateSources();
  assert.equal(f.controllers.sync.getSnapshot(), snapshot);
  assert.equal(f.controllers.retrieval.getSnapshot().configuration.processing.applied_sources, 1);
  assert.equal(f.controllers.processing.getSnapshot().phase, 'reviewing');
});
