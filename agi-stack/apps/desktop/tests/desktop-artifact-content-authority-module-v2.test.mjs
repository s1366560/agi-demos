import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  GenerationManagerV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2,
  DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
  DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2,
  DesktopArtifactContentAuthorityUnavailableErrorV2,
  applyDesktopArtifactContentAuthorityV2,
  createDesktopArtifactContentClientV2,
  desktopArtifactContentAuthorityDefinitionV2,
  withDesktopArtifactContentAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopArtifactContentAuthorityModuleV2.js');
const { desktopAutomationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopAutomationAuthorityModuleV2.js',
);
const { desktopNewTaskFlowAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopNewTaskFlowAuthorityModuleV2.js',
);
const { desktopNewThreadCreationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopNewThreadCreationAuthorityModuleV2.js',
);
const { desktopProjectSearchAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectSearchAuthorityModuleV2.js',
);
const { desktopSessionArtifactActionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionArtifactActionAuthorityModuleV2.js',
);
const {
  DesktopArtifactRequestError,
} = require(COMPILED_ROOT + '/src/features/chat/desktopArtifactClient.js');
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js',
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js',
);
const { desktopSessionTimelineAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js',
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js',
);
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);
const PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT,
);
const SERVER_HASH = `sha256:${'a'.repeat(64)}`;
const DRAFT_HASH = `sha256:${'b'.repeat(64)}`;

function loadBootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

function rendererDefinitions() {
  return [
    ...createDesktopRendererDefinitionsV2(),
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopSessionTimelineAuthorityDefinitionV2,
    desktopTerminalLifecycleAuthorityDefinitionV2,
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46451',
    apiKey: 'artifact-session',
    localApiToken: 'artifact-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function content(overrides = {}) {
  return {
    contract_version: 2,
    artifact_id: 'artifact / one',
    revision: 7,
    content_hash: SERVER_HASH,
    mime_type: 'text/markdown',
    content: '# Authority',
    ...overrides,
  };
}

function saveCommand(overrides = {}) {
  return {
    contract_version: 2,
    expected_revision: 7,
    content_hash: DRAFT_HASH,
    idempotency_key: 'artifact-save-7',
    content: '# Draft',
    ...overrides,
  };
}

function receipt(overrides = {}) {
  return {
    artifact_id: 'artifact / one',
    revision: 8,
    content_hash: DRAFT_HASH,
    duplicate: false,
    ...overrides,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
        },
      };
    },
  };
}

test('generated contract exposes one credential-free root artifact-content Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-artifact-content-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-fetch');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopArtifactContentAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopArtifactContentAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopArtifactContentAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-artifact-content-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and Profile disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopArtifactContentAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide a service') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_artifact_content_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-artifact-content-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
        {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
        { version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: 'sha256:' + '0'.repeat(64) }
        : definition,
    ),
    'desktop-renderer',
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('local transport preserves load, save and binary download contracts', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (calls.length === 1) return json(content());
    if (calls.length === 2) return json(receipt());
    return new Response(new Uint8Array([1, 2, 3]), {
      status: 200,
      headers: { 'content-type': 'application/pdf' },
    });
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const authority = service.bindOperation(runtimeConfig());
    const loaded = await authority.loadContent('artifact / one', controller.signal);
    const saved = await authority.saveContent(
      'artifact / one',
      saveCommand(),
      controller.signal,
    );
    const downloaded = await authority.download('artifact / one', controller.signal);

    assert.deepEqual(loaded, content());
    assert.deepEqual(saved, receipt());
    assert.equal(downloaded.type, 'application/pdf');
    assert.equal(downloaded.size, 3);
    assert.equal(calls.length, 3);
    for (const call of calls) {
      const url = new URL(call.input);
      const headers = new Headers(call.init.headers);
      assert.equal(url.origin, 'http://127.0.0.1:46451');
      assert.equal(url.pathname.startsWith('/api/v1/artifacts/artifact%20%2F%20one/'), true);
      assert.equal(headers.get('Authorization'), 'Bearer artifact-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'artifact-launch');
      assert.equal(call.init.signal, controller.signal);
    }
    assert.equal(calls[0].init.method, 'GET');
    assert.equal(calls[1].init.method, 'PUT');
    assert.equal(calls[1].init.headers.get('X-Expected-Revision'), '7');
    assert.equal(calls[1].init.headers.get('Idempotency-Key'), 'artifact-save-7');
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), saveCommand());
    assert.equal(calls[2].init.headers.get('Accept'), '*/*');
    assert.equal(calls[2].init.redirect, 'follow');
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('vault-bound Cloud transport forwards JSON, mutation and bounded binary policy', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          const path = args.request.path;
          if (path.endsWith('/content/bytes')) {
            return {
              status: 200,
              body: {
                kind: 'binary',
                bytes_base64: 'AQID',
                size_bytes: 3,
                mime_type: 'application/pdf',
                filename: 'artifact.pdf',
              },
            };
          }
          return {
            status: 200,
            body: args.request.method === 'PUT' ? receipt() : content(),
          };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2 },
    );
    const authority = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: 'https://cloud.example.test',
        apiKey: '',
        localApiToken: '',
        mode: 'cloud',
      }),
    );

    assert.deepEqual(await authority.loadContent('artifact / one'), content());
    assert.deepEqual(await authority.saveContent('artifact / one', saveCommand()), receipt());
    const blob = await authority.download('artifact / one');
    assert.equal(blob.type, 'application/pdf');
    assert.equal(blob.size, 3);
    assert.equal(calls.length, 3);
    assert.deepEqual(
      calls.map(({ command }) => command),
      ['cloud_request', 'cloud_request', 'cloud_request'],
    );
    assert.deepEqual(calls[0].args.request, {
      path: '/api/v1/artifacts/artifact%20%2F%20one/content',
      method: 'GET',
    });
    assert.deepEqual(calls[1].args.request, {
      path: '/api/v1/artifacts/artifact%20%2F%20one/content',
      method: 'PUT',
      body: saveCommand(),
      mutation: {
        expected_revision: 7,
        idempotency_key: 'artifact-save-7',
      },
    });
    assert.deepEqual(calls[2].args.request, {
      path: '/api/v1/artifacts/artifact%20%2F%20one/content/bytes',
      method: 'GET',
      response: { kind: 'binary', max_bytes: 16 * 1024 * 1024 },
    });
    assert.equal(JSON.stringify(calls).includes('Bearer'), false);
    await generation.dispose();
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('compatible client freezes config, request and command before one exact project lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = Object.freeze({
    bindOperation(config) {
      received.push({ config });
      return Object.freeze({
        async loadContent(artifactId, signal) {
          received.push({ kind: 'load', artifactId, signal });
          return content({ artifact_id: artifactId });
        },
        async saveContent(artifactId, command, signal) {
          received.push({ kind: 'save', artifactId, command, signal });
          return receipt({ artifact_id: artifactId });
        },
        async download(artifactId, signal) {
          received.push({ kind: 'download', artifactId, signal });
          return new Blob([artifactId], { type: 'text/plain' });
        },
      });
    },
  });
  const actions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const config = runtimeConfig();
  const command = saveCommand();
  const controller = new AbortController();
  const client = createDesktopArtifactContentClientV2(() => actions, () => config);
  const pending = client.saveContent('artifact / one', command, controller.signal);
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  command.expected_revision = 99;
  command.content = 'mutated';

  assert.deepEqual(await pending, receipt());
  assert.equal(Object.isFrozen(client), true);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.equal(received[0].config.projectId, 'project-1');
  assert.equal(Object.isFrozen(received[1].command), true);
  assert.deepEqual(received[1].command, saveCommand());
  assert.equal(received[1].artifactId, 'artifact / one');
  assert.equal(received[1].signal, controller.signal);
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'sha256:generation-1',
      request: {
        service: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2,
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'sha256:generation-1' },
  ]);
});

test('malformed config, artifact, command and signal fail before lease admission', async () => {
  let acquisitions = 0;
  const actions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  let config = runtimeConfig();
  const client = createDesktopArtifactContentClientV2(() => actions, () => config);

  await assert.rejects(
    client.loadContent('   '),
    (error) => error instanceof DesktopArtifactRequestError && error.reasonCode === 'artifact_id_invalid',
  );
  config = runtimeConfig({ tenantId: '' });
  await assert.rejects(
    client.loadContent('artifact-1'),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_artifact_content_input_invalid',
  );
  config = runtimeConfig();
  await assert.rejects(
    client.loadContent('artifact-1', {}),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_artifact_content_input_invalid',
  );
  await assert.rejects(
    client.saveContent('artifact-1', saveCommand({ contract_version: 1 })),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_artifact_content_input_invalid',
  );
  await assert.rejects(
    client.saveContent('artifact-1', saveCommand({ idempotency_key: '' })),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_artifact_content_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('every malformed service result fails closed at the operation boundary', async () => {
  let service = Object.freeze({
    bindOperation: () => ({
      loadContent: async () => content({ artifact_id: 'other-artifact' }),
      saveContent: async () => receipt(),
      download: async () => new Blob(['ok']),
    }),
  });
  const actions = () => acceptedActions(service, 'sha256:result-validation');
  const client = createDesktopArtifactContentClientV2(actions, () => runtimeConfig());

  await assert.rejects(
    client.loadContent('artifact / one'),
    (error) =>
      error instanceof DesktopArtifactRequestError &&
      error.reasonCode === 'artifact_content_contract_invalid',
  );
  service = Object.freeze({
    bindOperation: () => ({
      loadContent: async () => content(),
      saveContent: async () => receipt({ revision: 6 }),
      download: async () => new Blob(['ok']),
    }),
  });
  await assert.rejects(
    client.saveContent('artifact / one', saveCommand()),
    (error) =>
      error instanceof DesktopArtifactRequestError &&
      error.reasonCode === 'artifact_save_receipt_invalid',
  );
  service = Object.freeze({
    bindOperation: () => ({
      loadContent: async () => content(),
      saveContent: async () => receipt(),
      download: async () => ({ size: 3, type: 'application/pdf' }),
    }),
  });
  await assert.rejects(
    client.download('artifact / one'),
    (error) =>
      error instanceof DesktopArtifactRequestError &&
      error.reasonCode === 'artifact_download_contract_invalid',
  );
});

test('missing generation service is structured and released authority is revoked', async () => {
  const unavailable = createDesktopArtifactContentClientV2(() => null, () => runtimeConfig());
  await assert.rejects(
    unavailable.loadContent('artifact-1'),
    (error) =>
      error instanceof DesktopArtifactContentAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );

  const rejected = createDesktopArtifactContentClientV2(
    () => ({
      acquireServiceOperationLease: async () => ({
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_unavailable',
        runtimeCode: 'missing_service',
      }),
    }),
    () => runtimeConfig(),
  );
  await assert.rejects(
    rejected.loadContent('artifact-1'),
    (error) =>
      error instanceof DesktopArtifactContentAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_unavailable' &&
      error.runtimeCode === 'missing_service',
  );

  let escaped;
  await withDesktopArtifactContentAuthorityOperationV2(
    acceptedActions(
      {
        bindOperation: () => ({
          loadContent: async () => content({ artifact_id: 'artifact-1' }),
          saveContent: async () => receipt({ artifact_id: 'artifact-1' }),
          download: async () => new Blob(['ok']),
        }),
      },
      'sha256:revocation',
    ),
    {
      kind: 'load',
      config: runtimeConfig(),
      artifactId: 'artifact-1',
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.loadContent('artifact-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_artifact_content_operation_released',
  );
});

test('operation failure outranks release failure and successful release failure propagates', async () => {
  const service = {
    bindOperation: () => ({
      loadContent: async () => {
        throw new Error('artifact_operation_failed');
      },
      saveContent: async () => receipt(),
      download: async () => new Blob(['ok']),
    }),
  };
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(service),
      release: async () => {
        throw new Error('artifact_release_failed');
      },
    }),
  };
  const client = createDesktopArtifactContentClientV2(() => actions, () => runtimeConfig());

  await assert.rejects(client.loadContent('artifact-1'), /artifact_operation_failed/u);
  service.bindOperation = () => ({
    loadContent: async () => content({ artifact_id: 'artifact-1' }),
    saveContent: async () => receipt(),
    download: async () => new Blob(['ok']),
  });
  await assert.rejects(client.loadContent('artifact-1'), /artifact_release_failed/u);
});

test('HMR pins an in-flight artifact operation and sends the next call to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldService = {
    bindOperation: () => ({
      loadContent: async () => oldResponse,
      saveContent: async () => receipt(),
      download: async () => new Blob(['old']),
    }),
  };
  const newService = {
    bindOperation: () => ({
      loadContent: async () => content({ artifact_id: 'new-artifact', content: 'new' }),
      saveContent: async () => receipt(),
      download: async () => new Blob(['new']),
    }),
  };
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const client = createDesktopArtifactContentClientV2(() => actions, () => runtimeConfig());
  const oldPending = client.loadContent('old-artifact');
  actions = acceptedActions(newService, 'sha256:new', lifecycle);
  const next = await client.loadContent('new-artifact');
  resolveOld(content({ artifact_id: 'old-artifact', content: 'old' }));
  const old = await oldPending;

  assert.equal(next.content, 'new');
  assert.equal(old.content, 'old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    [
      'acquire:sha256:old',
      'acquire:sha256:new',
      'release:sha256:new',
      'release:sha256:old',
    ],
  );
});
