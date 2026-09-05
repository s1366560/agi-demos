import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const {
  createDesktopWorkbenchSnapshotOperationsV2: createOperations,
  desktopWorkbenchSnapshotAuthorityDefinitionV2: definition,
  DESKTOP_WORKBENCH_SNAPSHOT_AUTHORITY_SERVICE_V2: serviceName,
} = require(`${ROOT}/src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.js`);
const { acquireDesktopRendererServiceOperationLeaseV2: admit } = require(
  `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const { parseDesktopCapabilitySnapshot } = require(
  `${ROOT}/src/features/runtime/capabilitySnapshot.js`,
);
const snapshot = parseDesktopCapabilitySnapshot(
  JSON.parse(
    readFileSync(new URL('./fixtures/desktop-capability-snapshot.v3.json', import.meta.url)),
  ),
);
assert.ok(snapshot);
const config = () => ({
  mode: 'cloud',
  apiBaseUrl: 'https://example.invalid',
  apiKey: '',
  deviceAuthorizationBaseUrl: '',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  workspaceRoot: '',
});
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fixture(overrides = {}) {
  const state = { releases: 0, binds: 0, acquisitions: 0, childRequests: [] };
  const service = {
    bindOperation(boundConfig, childActions) {
      state.binds++;
      state.config = boundConfig;
      state.actions = childActions;
      return { loadSnapshot: async () => snapshot };
    },
  };
  const admission = {
    status: 'accepted',
    digest: 'sha256:fixture',
    acquireChildServiceLease: async (request) => {
      state.childRequests.push(request);
      return { status: 'rejected', reasonCode: 'fixture_child_unavailable' };
    },
    useService: (callback) => callback(service),
    release: async () => {
      state.releases++;
    },
    ...overrides,
  };
  const actions = {
    acquireOperationLease() {
      throw new Error('root fallback forbidden');
    },
    async acquireServiceOperationLease(request) {
      state.acquisitions++;
      state.request = request;
      return admission;
    },
  };
  return { state, service, admission, actions, operations: createOperations(() => actions) };
}

test('snapshot admission without parent fork fails explicitly before binding', async () => {
  const f = fixture({ acquireChildServiceLease: undefined });
  await assert.rejects(
    f.operations.loadSnapshot({ config: config(), signal: new AbortController().signal }),
    (error) => error.code === 'desktop_workbench_snapshot_parent_lease_required',
  );
  assert.equal(f.state.binds, 0);
  assert.equal(f.state.releases, 1);
  assert.equal(f.state.acquisitions, 1);
});

test('snapshot freezes entry config before async admission and captures parent child acquisition', async () => {
  const f = fixture();
  const gate = deferred();
  let resolutions = 0;
  let current = {
    ...f.actions,
    acquireServiceOperationLease: async (request) => {
      f.state.request = request;
      await gate.promise;
      return f.admission;
    },
  };
  const operations = createOperations(() => {
    resolutions++;
    return current;
  });
  const inputConfig = config();
  const pending = operations.loadSnapshot({
    config: inputConfig,
    signal: new AbortController().signal,
  });
  inputConfig.tenantId = 'replacement';
  current = {
    acquireServiceOperationLease() {
      throw new Error('current generation fallback');
    },
  };
  f.service.bindOperation = (boundConfig, childActions) => {
    f.state.config = boundConfig;
    f.state.actions = childActions;
    return {
      loadSnapshot: async () => {
        await childActions.acquireServiceOperationLease({
          service: 'child',
          scope: { kind: 'root' },
        });
        assert.throws(
          () => childActions.acquireOperationLease(),
          (error) => error.code === 'desktop_workbench_snapshot_service_lease_required',
        );
        return snapshot;
      },
    };
  };
  gate.resolve();
  assert.equal(await pending, snapshot);
  assert.equal(resolutions, 1);
  assert.equal(f.state.config.tenantId, 'tenant-1');
  assert.notEqual(f.state.config, inputConfig);
  assert.ok(Object.isFrozen(f.state.config));
  assert.ok(Object.isFrozen(f.state.actions));
  assert.deepEqual(f.state.request, {
    service: serviceName,
    version: '1.0.0',
    scope: { kind: 'root' },
  });
  assert.equal(f.state.childRequests.length, 1);
  assert.throws(
    () => f.state.actions.acquireServiceOperationLease({}),
    (error) => error.code === 'desktop_workbench_snapshot_operation_released',
  );
});

test('snapshot service callback can only be consumed once and cannot escape release', async () => {
  const f = fixture();
  let captured;
  f.admission.useService = async (callback) => {
    captured = callback;
    const first = callback(f.service);
    await assert.rejects(
      callback(f.service),
      (error) => error.code === 'desktop_workbench_snapshot_operation_released',
    );
    return first;
  };
  await f.operations.loadSnapshot({ config: config(), signal: new AbortController().signal });
  await assert.rejects(
    captured(f.service),
    (error) => error.code === 'desktop_workbench_snapshot_operation_released',
  );
  assert.equal(f.state.binds, 1);
  assert.equal(f.state.releases, 1);
});

test('snapshot cancelled during admission releases late lease without binding', async () => {
  const f = fixture();
  const gate = deferred();
  const controller = new AbortController();
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.admission;
  };
  const pending = f.operations.loadSnapshot({ config: config(), signal: controller.signal });
  controller.abort();
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(f.state.binds, 0);
  assert.equal(f.state.releases, 1);
});

test('snapshot cancelled during service rejects late result and prevents escaped child acquisition', async () => {
  const f = fixture();
  const entered = deferred();
  const gate = deferred();
  const controller = new AbortController();
  f.service.bindOperation = (_config, actions) => {
    f.state.actions = actions;
    return {
      loadSnapshot: async () => {
        entered.resolve();
        await gate.promise;
        return snapshot;
      },
    };
  };
  const pending = f.operations.loadSnapshot({ config: config(), signal: controller.signal });
  await entered.promise;
  controller.abort();
  assert.throws(() => f.state.actions.acquireServiceOperationLease({}), { name: 'AbortError' });
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(f.state.releases, 1);
  assert.equal(f.state.childRequests.length, 0);
});

test('snapshot release failure preserves primary service error identity', async () => {
  const primary = new Error('primary');
  const secondary = new Error('release');
  const f = fixture({
    release: async () => {
      throw secondary;
    },
  });
  f.service.bindOperation = () => ({
    loadSnapshot: async () => {
      throw primary;
    },
  });
  await assert.rejects(
    f.operations.loadSnapshot({ config: config(), signal: new AbortController().signal }),
    (error) => error === primary,
  );
});

test('snapshot successful service still reports release failure', async () => {
  const secondary = new Error('release');
  const f = fixture({
    release: async () => {
      throw secondary;
    },
  });
  await assert.rejects(
    f.operations.loadSnapshot({ config: config(), signal: new AbortController().signal }),
    (error) => error === secondary,
  );
});

function definitions(customService) {
  return [
    ...runtime.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ].map((candidate) =>
    candidate.moduleRef === definition.moduleRef
      ? { ...candidate, apply: (context) => context.provide(serviceName, customService) }
      : candidate,
  );
}

test('real Loader snapshot service admission executes enabled provider and disabled outer makes zero HTTP', async () => {
  let httpCalls = 0;
  let binds = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    httpCalls++;
    return new Response('{}');
  };
  const customService = {
    bindOperation: (_config, actions) => {
      binds++;
      return {
        loadSnapshot: async () => {
          const child = await actions.acquireServiceOperationLease({
            service: 'service:desktop-renderer.session-projection-authority',
            version: '1.0.0',
            scope: {
              kind: 'session',
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              session_id: 'session-1',
            },
          });
          assert.equal(child.status, 'accepted');
          try {
            await fetch('https://example.invalid/snapshot-test');
            return snapshot;
          } finally {
            await child.release();
          }
        },
      };
    },
  };
  const manager = new runtime.GenerationManagerV2();
  try {
    const profile = JSON.parse(
      readFileSync(
        new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
        'utf8',
      ),
    );
    const loader = new runtime.LoaderV2(definitions(customService), 'desktop-renderer');
    const generation = await loader.stage(profile);
    await manager.publish(generation);
    const operations = createOperations(() => ({
      acquireOperationLease() {
        throw new Error('root fallback forbidden');
      },
      acquireServiceOperationLease: (request) =>
        admit(manager.current, request, (g) => manager.acquire(g)),
    }));
    assert.equal(
      await operations.loadSnapshot({ config: config(), signal: new AbortController().signal }),
      snapshot,
    );
    assert.equal(httpCalls, 1);
    assert.equal(generation.leaseCount, 0);
    const entry = profile.entries.find((item) => item.module_ref === definition.moduleRef);
    assert.ok(entry);
    entry.enabled = false;
    await manager.publish(await loader.stage(profile));
    httpCalls = 0;
    binds = 0;
    await assert.rejects(
      operations.loadSnapshot({ config: config(), signal: new AbortController().signal }),
      (error) => error.code === 'desktop_renderer_service_resolve_failed',
    );
    assert.equal(httpCalls, 0);
    assert.equal(binds, 0);
    assert.equal(manager.current.leaseCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
    await manager.close();
  }
});

test('production snapshot factory degrades rejected child services through real parent forks', async () => {
  const productionDefinitions = [
    ...runtime.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ];
  const manager = new runtime.GenerationManagerV2();
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url) => {
    requests.push(String(url));
    return new Response(JSON.stringify({ detail: 'Not Found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  let rootAcquisitions = 0;
  let forks = 0;
  const childResolutions = [];
  try {
    const profile = JSON.parse(
      readFileSync(
        new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
        'utf8',
      ),
    );
    const generation = await new runtime.LoaderV2(productionDefinitions, 'desktop-renderer').stage(
      profile,
    );
    await manager.publish(generation);
    const resolve = generation.resolve.bind(generation);
    generation.resolve = (service, scope, options) => {
      if (service === serviceName) return resolve(service, scope, options);
      childResolutions.push(service);
      throw new runtime.RuntimeV2Error(
        'test_child_service_unavailable',
        'child service unavailable',
      );
    };
    const operations = createOperations(() => ({
      acquireOperationLease() {
        throw new Error('root fallback forbidden');
      },
      acquireServiceOperationLease: (request) => {
        rootAcquisitions++;
        assert.equal(request.service, serviceName);
        return admit(generation, request, (capturedGeneration) => {
          const parent = manager.acquire(capturedGeneration);
          const fork = parent.fork.bind(parent);
          parent.fork = () => {
            forks++;
            const child = fork();
            assert.equal(child.generation, generation);
            return child;
          };
          return parent;
        });
      },
    }));
    const inputConfig = { ...config(), apiKey: 'test-fixture-token' };
    const result = await operations.loadSnapshot({
      config: inputConfig,
      signal: new AbortController().signal,
    });
    assert.ok(parseDesktopCapabilitySnapshot(result));
    assert.equal(rootAcquisitions, 1);
    assert.ok(
      childResolutions.length > 20,
      'production dependency graph must attempt child services',
    );
    assert.equal(forks, childResolutions.length);
    for (const service of [
      'service:desktop-renderer.tenant-providers-authority',
      'service:desktop-renderer.tenant-skill-definitions-authority',
      'service:desktop-renderer.project-blackboard-authority',
    ])
      assert.ok(childResolutions.includes(service), `missing production child: ${service}`);
    for (const capability of [
      'tenant-tenant-providers',
      'tenant-tenant-skills',
      'project-blackboard-dynamic-project-blackboard',
    ])
      assert.equal(result.capabilities[capability].availability, 'unavailable');
    assert.ok(
      requests.length > 0,
      'raw Search/Journey probes must use the controlled 404 transport',
    );
    assert.equal(generation.leaseCount, 0, 'all rejected forks and the parent must be released');
  } finally {
    globalThis.fetch = originalFetch;
    await manager.close();
  }
});
