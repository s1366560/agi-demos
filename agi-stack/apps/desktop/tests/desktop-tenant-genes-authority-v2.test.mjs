import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantGenesAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopTenantGenesHttpProjectionV2.js`);
const pluginRoot = `${ROOT}/src/plugins`;
const authorityModules = readdirSync(pluginRoot)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${pluginRoot}/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );
const repositoryRoot = new URL('../../../../', import.meta.url);
const bootstrapPath = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  repositoryRoot,
);

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: mode === 'cloud' ? 'trusted-session' : 'local-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: mode === 'cloud' ? 'tenant-1' : 'local',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const scope = (authority = 'cloud') => ({
  authority,
  tenantId: authority === 'cloud' ? 'tenant-1' : 'local',
});
const gene = (marker = 'gene-1', overrides = {}) =>
  Object.freeze({
    id: marker,
    name: 'Review',
    slug: 'review',
    tenantId: 'tenant-1',
    description: 'Review code',
    category: 'development',
    version: '1.0.0',
    visibility: 'tenant',
    installCount: 1,
    averageRating: 5,
    isPublished: true,
    createdAt: 'now',
    updatedAt: null,
    ...overrides,
  });
const review = (overrides = {}) =>
  Object.freeze({
    id: 'review-1',
    geneId: 'gene-1',
    userId: 'user-1',
    rating: 5,
    content: 'Useful',
    createdAt: 'now',
    ...overrides,
  });
const snapshot = (marker = 'gene-1') => {
  const data = Object.freeze({
    membershipRole: 'owner',
    genes: Object.freeze([gene(marker)]),
    total: 1,
    page: 1,
    pageSize: 20,
  });
  return Object.freeze({
    scope: Object.freeze(scope()),
    scopeRevision: 7,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: Object.freeze([
      'view',
      'list',
      'inspect-genome',
      'inspect-evolution',
      'list-reviews',
      'rate',
      'create-review',
      'delete-own-review',
      'create',
      'update',
      'delete',
      'publish',
      'unpublish',
      'install',
    ]),
    data,
    ...data,
  });
};
const authority = (overrides = {}) =>
  Object.freeze({
    async load() {
      return snapshot();
    },
    async createGene() {
      return gene();
    },
    async updateGene() {
      return gene();
    },
    async deleteGene() {},
    async publishGene() {
      return gene();
    },
    async unpublishGene() {
      return gene();
    },
    async installGene() {
      return Object.freeze({ id: 'install-1' });
    },
    async rateGene() {
      return Object.freeze({ id: 'rating-1' });
    },
    async listGenomes() {
      return Object.freeze([Object.freeze({ id: 'genome-1' })]);
    },
    async listEvolution() {
      return Object.freeze({ generation: 1 });
    },
    async listReviews() {
      return Object.freeze([review()]);
    },
    async createReview() {
      return review();
    },
    async deleteReview() {},
    ...overrides,
  });
const service = (value, capture = {}) =>
  Object.freeze({
    bindOperation(currentConfig, currentScope) {
      capture.config = currentConfig;
      capture.scope = currentScope;
      return value;
    },
  });
const actions = (value, lifecycle = [], releaseError, capture = {}) => ({
  async acquireServiceOperationLease(descriptor) {
    lifecycle.push(['acquire', descriptor]);
    return {
      status: 'accepted',
      useService(use) {
        capture.use = use;
        return use(value);
      },
      async release() {
        lifecycle.push(['release']);
        if (releaseError) throw releaseError;
      },
    };
  },
});

test('catalog and apply register the exact root Tenant Genes Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(moduleV2.desktopTenantGenesAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
  const provided = {};
  moduleV2.applyDesktopTenantGenesAuthorityV2(
    {
      provide(key, value) {
        provided.key = key;
        provided.value = value;
      },
    },
    { strategy: 'desktop-api-fetch' },
  );
  assert.equal(provided.key, moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () =>
      moduleV2.applyDesktopTenantGenesAuthorityV2(
        { provide() {} },
        { strategy: 'desktop-api-fetch', fallback: true },
      ),
    (error) => error.code === 'desktop_tenant_genes_authority_config_invalid',
  );
});

test('Loader activates the Provider and Profile disable removes it without fallback', async () => {
  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(
    generation.resolve(
      moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_VERSION_V2 },
    ),
  );
  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-tenant-genes-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: '1.0.0' },
      ),
    (error) => error instanceof runtime.RuntimeV2Error && error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('all thirteen operations hold exact tenant leases and freeze inputs', async () => {
  const lifecycle = [];
  const captured = {};
  const serviceCapture = {};
  const signal = new AbortController().signal;
  const client = authority({
    async load(currentScope, options) {
      captured.scope = currentScope;
      captured.signal = options?.signal;
      return snapshot();
    },
    async createGene(_scope, input) {
      captured.create = input;
      return gene();
    },
    async updateGene(_scope, _geneId, input) {
      captured.update = input;
      return gene();
    },
  });
  const operations = moduleV2.createDesktopTenantGenesOperationsV2(() =>
    actions(service(client, serviceCapture), lifecycle),
  );
  await operations.loadTenantGenes({ config: config(), scope: scope(), signal });
  await operations.createTenantGene({
    config: config(),
    scope: scope(),
    input: { name: 'Review', slug: 'review', manifest: { nested: { enabled: true } } },
  });
  await operations.updateTenantGene({
    config: config(),
    scope: scope(),
    geneId: 'gene-1',
    input: { manifest: { nested: { enabled: false } } },
  });
  await operations.deleteTenantGene({ config: config(), scope: scope(), geneId: 'gene-1' });
  await operations.publishTenantGene({ config: config(), scope: scope(), geneId: 'gene-1' });
  await operations.unpublishTenantGene({ config: config(), scope: scope(), geneId: 'gene-1' });
  await operations.installTenantGene({
    config: config(),
    scope: scope(),
    instanceId: 'instance-1',
    geneId: 'gene-1',
  });
  await operations.rateTenantGene({
    config: config(),
    scope: scope(),
    geneId: 'gene-1',
    rating: 5,
    comment: 'Useful',
  });
  await operations.listTenantGeneGenomes({ config: config(), scope: scope() });
  await operations.loadTenantGeneEvolution({ config: config(), scope: scope() });
  await operations.listTenantGeneReviews({ config: config(), scope: scope(), geneId: 'gene-1' });
  await operations.createTenantGeneReview({
    config: config(),
    scope: scope(),
    geneId: 'gene-1',
    rating: 5,
    content: 'Useful',
  });
  await operations.deleteTenantGeneReview({
    config: config(),
    scope: scope(),
    geneId: 'gene-1',
    reviewId: 'review-1',
  });

  const acquisitions = lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value);
  assert.equal(acquisitions.length, 13);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 13);
  assert.equal(
    acquisitions.every(
      (value) =>
        value.service === moduleV2.DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2 &&
        value.version === '1.0.0' &&
        value.scope.kind === 'tenant' &&
        value.scope.tenant_id === 'tenant-1',
    ),
    true,
  );
  assert.equal(captured.signal, signal);
  assert.equal(Object.isFrozen(captured.scope), true);
  assert.equal(Object.isFrozen(serviceCapture.config), true);
  assert.equal(Object.isFrozen(serviceCapture.scope), true);
  assert.equal(Object.isFrozen(captured.create), true);
  assert.equal(Object.isFrozen(captured.create.manifest), true);
  assert.equal(Object.isFrozen(captured.create.manifest.nested), true);
  assert.equal(Object.isFrozen(captured.update.manifest.nested), true);
});

test('invalid inputs and generation admissions fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantGenesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  assert.throws(
    () => operations.loadTenantGenes({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_tenant_genes_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantGenes({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  const unavailable = moduleV2.createDesktopTenantGenesOperationsV2(() => null);
  await assert.rejects(
    () => unavailable.loadTenantGenes({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('service, authority and operation response shapes are exact', async () => {
  const malformedService = moduleV2.createDesktopTenantGenesOperationsV2(() =>
    actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })),
  );
  await assert.rejects(
    () => malformedService.loadTenantGenes({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_genes_service_invalid',
  );

  const malformedAuthority = moduleV2.createDesktopTenantGenesOperationsV2(() =>
    actions(service(Object.freeze({ ...authority(), extra: true }))),
  );
  await assert.rejects(
    () => malformedAuthority.loadTenantGenes({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_genes_service_invalid',
  );

  const invalidCases = [
    ['loadTenantGenes', {}, { load: async () => ({ ...snapshot(), allowedActions: [] }) }],
    ['createTenantGene', { input: { name: 'Review', slug: 'review' } }, { createGene: async () => gene('gene-1', { tenantId: 'other' }) }],
    ['installTenantGene', { instanceId: 'instance-1', geneId: 'gene-1' }, { installGene: async () => [] }],
    ['listTenantGeneGenomes', {}, { listGenomes: async () => [null] }],
    ['listTenantGeneReviews', { geneId: 'gene-1' }, { listReviews: async () => [review({ geneId: 'other' })] }],
  ];
  for (const [operation, extra, override] of invalidCases) {
    const current = moduleV2.createDesktopTenantGenesOperationsV2(() =>
      actions(service(authority(override))),
    );
    await assert.rejects(
      () => current[operation]({ config: config(), scope: scope(), ...extra }),
      (error) => error.code === 'desktop_tenant_genes_operation_response_invalid',
      operation,
    );
  }
});

test('HMR pins in-flight work, revokes escaped use and preserves error precedence', async () => {
  let finish;
  const capture = {};
  let current = actions(
    service(
      authority({
        load: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    ),
    [],
    undefined,
    capture,
  );
  const operations = moduleV2.createDesktopTenantGenesOperationsV2(() => current);
  const pending = operations.loadTenantGenes({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ load: async () => snapshot('new') })));
  finish(snapshot('old'));
  assert.equal((await pending).genes[0].id, 'old');
  assert.equal(
    (await operations.loadTenantGenes({ config: config(), scope: scope() })).genes[0].id,
    'new',
  );
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_tenant_genes_operation_released',
  );

  const primary = new Error('primary');
  const primaryFailing = moduleV2.createDesktopTenantGenesOperationsV2(() =>
    actions(service(authority({ load: async () => { throw primary; } })), [], new Error('release')),
  );
  await assert.rejects(
    () => primaryFailing.loadTenantGenes({ config: config(), scope: scope() }),
    primary,
  );
  const release = new Error('release-only');
  const releaseFailing = moduleV2.createDesktopTenantGenesOperationsV2(() =>
    actions(service(authority()), [], release),
  );
  await assert.rejects(
    () => releaseFailing.loadTenantGenes({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud projection holds one operation across both context observations and uses the vault', async () => {
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, request: args.request });
          return vaultResponse(args.request.path, args.request.method);
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault_bound_cloud_must_not_fetch');
  };
  const client = projectionV2.createDesktopTenantGenesHttpProjectionV2({
    ...config(),
    apiKey: '',
  });
  const result = await client.load(scope());
  assert.equal(result.scopeRevision, 7);
  assert.deepEqual(
    calls.map(({ request }) => new URL(request.path, 'https://api.test').pathname),
    ['/api/v1/workspace-context', '/api/v1/genes/', '/api/v1/workspace-context'],
  );
  assert.equal(calls.every(({ command }) => command === 'cloud_request'), true);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

test('Local projection uses only authenticated sidecar transport and normalizes missing authority', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    calls.push({
      origin: parsed.origin,
      path: parsed.pathname,
      launch: new Headers(init.headers).get('X-Agistack-Launch'),
    });
    if (parsed.pathname === '/api/v1/workspace-context') {
      return json({
        context: { tenant_id: 'local', project_id: 'project-1', revision: 7 },
        membership_role: 'owner',
      });
    }
    return json({ detail: 'missing' }, 404);
  };
  const client = projectionV2.createDesktopTenantGenesHttpProjectionV2(config('local'));
  await assert.rejects(
    () => client.load(scope('local')),
    (error) => error.status === 501 && error.message === 'local_gene_market_authority_unavailable',
  );
  await assert.rejects(
    () => client.createGene(scope('local'), { name: 'Review', slug: 'review' }),
    (error) => error.status === 501 && error.message === 'local_gene_market_authority_unavailable',
  );
  assert.equal(calls.every(({ origin }) => origin === 'http://127.0.0.1:43117'), true);
  assert.equal(calls.every(({ launch }) => launch === 'private-launch'), true);
  assert.equal(calls.some(({ origin }) => origin === 'https://api.test'), false);
});

function vaultResponse(path, method) {
  const pathname = new URL(path, 'https://api.test').pathname;
  if (pathname === '/api/v1/workspace-context') {
    return {
      status: 200,
      body: {
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 7 },
        membership_role: 'owner',
      },
    };
  }
  if (pathname === '/api/v1/genes/' && method === 'GET') {
    return {
      status: 200,
      body: { genes: [genePayload()], total: 1, page: 1, page_size: 20 },
    };
  }
  throw new Error(`unexpected vault request ${method} ${pathname}`);
}

function genePayload() {
  return {
    id: 'gene-1',
    name: 'Review',
    slug: 'review',
    tenant_id: 'tenant-1',
    description: 'Review code',
    category: 'development',
    version: '1.0.0',
    visibility: 'tenant',
    install_count: 1,
    avg_rating: 5,
    is_published: true,
    created_at: 'now',
    updated_at: null,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
