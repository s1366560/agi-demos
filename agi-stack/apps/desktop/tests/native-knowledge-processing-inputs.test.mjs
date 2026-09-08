import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createNativeKnowledgeProcessingController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeProcessingController.js');
const configuration = {
  revision: 8,
  build_id: 'old-build',
  provider_id: 'old-provider',
  provider_revision: 2,
  model_id: 'old-model',
  dimensions: 3,
  input_contract_version: 1,
  normalization_version: 1,
};
const embedding = {
  providerId: 'provider-1',
  providerRevision: 3,
  providerName: 'Provider one',
  modelId: 'embedding-1',
};
const inputs = {
  scope: nativeScope,
  embeddingModels: { availability: 'available', items: [embedding] },
  workspaces: { availability: 'available', items: [{ id: 'workspace-1', name: 'Workspace one' }] },
};
function fixture(options = {}) {
  const writes = [],
    loads = [];
  const controller = createNativeKnowledgeProcessingController({
    authority: {
      scope: projectScope,
      userId: 'user-1',
      sessionId: 'session-1',
      contextRevision: 7,
      generationDigest: 'renderer-1',
      available: true,
      allowedActions: ['configuration', 'configure_embedding', 'process_one'],
    },
    queryClient: {
      query: async () => ({
        scope: nativeScope,
        result: {
          configuration:
            options.configuration === undefined ? configuration : options.configuration,
          active_build_id: null,
          processing: null,
          index: null,
        },
      }),
    },
    inputsClient: options.missing
      ? undefined
      : {
          load: async (scope, request) => {
            loads.push({ scope, request });
            return options.load ? options.load(loads.length) : structuredClone(inputs);
          },
        },
    commandClient: {
      execute: async (scope, command, request) => {
        writes.push({ scope, command, request });
        if (options.write) return options.write(command);
        return {
          scope: nativeScope,
          result:
            command.operation === 'configure_embedding'
              ? {
                  configuration: {
                    ...configuration,
                    revision: 9,
                    build_id: command.build_id,
                    provider_id: command.provider_id,
                    provider_revision: command.provider_revision,
                    model_id: command.model_id,
                  },
                }
              : { receipt: null },
        };
      },
    },
  });
  return { controller, writes, loads };
}
async function choose(f, operation = 'configure_embedding') {
  await f.controller.prepareInputs(operation);
  if (operation === 'configure_embedding')
    f.controller.chooseEmbedding(embedding.providerId, embedding.modelId);
  else f.controller.chooseWorkspace('workspace-1');
  await f.controller.review(operation);
}

test('configuration uses trusted choice, fresh provider revision and CAS; no write until explicit confirm', async () => {
  const f = fixture();
  await choose(f);
  const selected = f.controller.getSnapshot().selection;
  assert.equal(selected.expected_config_revision, 8);
  assert.equal(selected.provider_revision, 3);
  assert.match(selected.build_id, /^[0-9a-f-]{36}$/);
  assert.equal(f.writes.length, 0);
  await f.controller.confirm();
  assert.equal(f.loads.length, 3);
  assert.equal(f.writes[0].command, selected);
  assert.ok(Object.isFrozen(selected));
  assert.equal(f.controller.getSnapshot().snapshot.configuration.revision, 9);
  for (const load of f.loads) {
    assert.equal(load.request.operation, 'configure_embedding');
    assert.deepEqual(load.request.expectedScope, nativeScope);
    assert.deepEqual(load.scope, projectScope);
  }
});
test('initial configuration uses null CAS and model selection cannot be forged', async () => {
  const f = fixture({ configuration: null });
  await f.controller.prepareInputs('configure_embedding');
  f.controller.chooseEmbedding('forged', 'forged');
  await f.controller.review('configure_embedding');
  assert.equal(f.controller.getSnapshot().selection, null);
  f.controller.chooseEmbedding(embedding.providerId, embedding.modelId);
  await f.controller.review('configure_embedding');
  assert.equal(f.controller.getSnapshot().selection.expected_config_revision, null);
});
test('explicit workspace processing works independently of unavailable embedding catalog', async () => {
  const f = fixture({
    configuration: null,
    load: async () => ({ ...inputs, embeddingModels: { availability: 'unavailable', items: [] } }),
  });
  await choose(f, 'process_one');
  assert.deepEqual(f.controller.getSnapshot().selection, {
    operation: 'process_one',
    workspace_id: 'workspace-1',
  });
  assert.equal(f.writes.length, 0);
  await f.controller.confirm();
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.writes[0].command, { operation: 'process_one', workspace_id: 'workspace-1' });
  assert.equal(f.controller.getSnapshot().outcome.result.receipt, null);
  assert.ok(f.loads.every((load) => load.request.operation === 'process_one'));
});
for (const operation of ['configure_embedding', 'process_one']) {
  test(`${operation} changed catalog at confirmation prevents writes and clears choice`, async () => {
    const f = fixture({
      load: async (count) =>
        count < 3
          ? structuredClone(inputs)
          : {
              ...inputs,
              embeddingModels: {
                availability: 'available',
                items: [{ ...embedding, providerRevision: 4 }],
              },
              workspaces: { availability: 'available', items: [] },
            },
    });
    await choose(f, operation);
    await f.controller.confirm();
    assert.equal(f.writes.length, 0);
    assert.equal(f.controller.getSnapshot().error, 'inputsChanged');
    assert.equal(f.controller.getSnapshot().selection, null);
  });
  test(`${operation} unknown outcome requires refresh and never repeats previous request`, async () => {
    const f = fixture({
      write: async () => {
        throw Object.assign(Error('network_failure'), { status: 502 });
      },
    });
    await choose(f, operation);
    await f.controller.confirm();
    assert.equal(f.controller.getSnapshot().phase, 'uncertain');
    assert.equal(f.controller.getSnapshot().inputs, null);
    await f.controller.prepareInputs(operation);
    await f.controller.confirm();
    assert.equal(f.writes.length, 1);
    await f.controller.refresh();
    assert.equal(f.controller.getSnapshot().notice, 'recoveredUnknown');
    assert.equal(f.controller.getSnapshot().outcome, null);
    assert.equal(f.writes.length, 1);
  });
}
test('permission loss clears inputs, drafts and review', async () => {
  const f = fixture({
    load: async (count) => {
      if (count > 2) throw Object.assign(Error('forbidden'), { status: 403 });
      return structuredClone(inputs);
    },
  });
  await choose(f);
  await f.controller.confirm();
  assert.equal(f.controller.getSnapshot().error, 'contextChanged');
  assert.equal(f.controller.getSnapshot().inputs, null);
  assert.equal(f.controller.getSnapshot().embeddingChoice, null);
  assert.equal(f.writes.length, 0);
});
test('changed full native scope clears inputs and rejects late catalog after stop', async () => {
  const f = fixture({
    load: async (count) => ({
      ...inputs,
      scope: { ...nativeScope, generation: nativeScope.generation + (count > 1 ? 1 : 0) },
    }),
  });
  await choose(f);
  assert.equal(f.controller.getSnapshot().error, 'contextChanged');
  assert.equal(f.writes.length, 0);
  let release;
  const late = fixture({
    load: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  });
  const pending = late.controller.prepareInputs('process_one');
  await new Promise((resolve) => setImmediate(resolve));
  late.controller.stop();
  late.controller.activate();
  release(inputs);
  await pending;
  assert.equal(late.controller.getSnapshot().inputs, null);
});
test('unavailable malformed and duplicate directories fail closed without exposing extras', async () => {
  for (const bad of [
    { ...inputs, embeddingModels: { availability: 'unavailable', items: [embedding] } },
    { ...inputs, embeddingModels: { availability: 'available', items: [embedding, embedding] } },
    {
      ...inputs,
      workspaces: {
        availability: 'available',
        items: [{ id: 'workspace-1', name: 'Workspace', extra: 'unexpected' }],
      },
    },
  ]) {
    const f = fixture({ load: async () => bad });
    await f.controller.prepareInputs('configure_embedding');
    assert.equal(f.controller.getSnapshot().inputs, null);
    assert.equal(f.writes.length, 0);
  }
  const missing = fixture({ missing: true });
  await choose(missing);
  assert.equal(missing.writes.length, 0);
  assert.equal(missing.controller.getSnapshot().inputsAvailable, false);
});
