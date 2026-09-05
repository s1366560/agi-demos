import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src';
const runtime = require('@agistack/plugin-runtime');
const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
  `${ROOT}/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/types.js`);
const definitions = require(`${ROOT}/plugins/desktopTenantSkillDefinitionsAuthorityModuleV2.js`);
const packages = require(`${ROOT}/plugins/desktopTenantSkillPackagesAuthorityModuleV2.js`);
const evolution = require(`${ROOT}/plugins/desktopTenantSkillEvolutionAuthorityModuleV2.js`);

const config = Object.freeze({
  ...DEFAULT_CONFIG,
  mode: 'cloud',
  apiBaseUrl: 'https://api.memstack.test',
  apiKey: 'skills-loader-trusted-session',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const skill = Object.freeze({
  id: 'skill-1',
  tenant_id: 'tenant-1',
  scope: 'tenant',
  project_id: null,
  name: 'review',
  description: 'Review',
  tools: [],
  status: 'active',
});
const descriptors = [
  {
    entryId: 'builtin-desktop-tenant-skill-definitions-authority',
    service: definitions.DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_SERVICE_V2,
    moduleRef: definitions.DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
    definition: definitions.desktopTenantSkillDefinitionsAuthorityDefinitionV2,
    call(actions, signal) {
      return definitions
        .createDesktopTenantSkillDefinitionsClientV2(
          definitions.createDesktopTenantSkillDefinitionsOperationsV2(() => actions),
          config,
        )
        .listManagedSkills(signal);
    },
  },
  {
    entryId: 'builtin-desktop-tenant-skill-packages-authority',
    service: packages.DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_SERVICE_V2,
    moduleRef: packages.DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_MODULE_REF_V2,
    definition: packages.desktopTenantSkillPackagesAuthorityDefinitionV2,
    call(actions, signal) {
      return packages
        .createDesktopTenantSkillPackagesClientV2(
          packages.createDesktopTenantSkillPackagesOperationsV2(() => actions),
          config,
        )
        .listManagedSkillVersions('skill-1', signal);
    },
  },
  {
    entryId: 'builtin-desktop-tenant-skill-evolution-authority',
    service: evolution.DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_SERVICE_V2,
    moduleRef: evolution.DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_MODULE_REF_V2,
    definition: evolution.desktopTenantSkillEvolutionAuthorityDefinitionV2,
    call(actions, signal) {
      return evolution
        .createDesktopTenantSkillEvolutionClientV2(
          evolution.createDesktopTenantSkillEvolutionOperationsV2(() => actions),
          config,
        )
        .getManagedSkillEvolution('skill-1', signal);
    },
  },
];

test('real Loader and generation leases execute all three skill providers; disabled profiles deny without HTTP', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input);
    requests.push({ url, init });
    if (url.pathname === '/api/v1/skills/') return Response.json({ items: [skill] });
    if (url.pathname === '/api/v1/skills/skill-1/versions') {
      return Response.json({ versions: [], total: 0 });
    }
    if (url.pathname === '/api/v1/skills/skill-1/evolution') {
      return Response.json({
        skill_id: 'skill-1',
        skill_name: 'review',
        captured_session_count: 0,
        jobs: [],
        route: [],
        trigger: {},
      });
    }
    assert.fail(`unexpected HTTP route ${url.pathname}`);
  };
  const authorities = readdirSync(`${ROOT}/plugins`)
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(`${ROOT}/plugins/${name}`)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorities],
    'desktop-renderer',
  );
  const manager = new runtime.GenerationManagerV2();
  const signal = new AbortController().signal;
  const actionsFor = (generation, admissions) =>
    Object.freeze({
      async acquireServiceOperationLease(request) {
        const admission = await acquireDesktopRendererServiceOperationLeaseV2(
          generation,
          request,
          (requestedGeneration) => manager.acquire(requestedGeneration),
        );
        admissions.push({ request, admission });
        return admission;
      },
    });
  try {
    const active = await loader.stage(profile);
    await manager.publish(active);
    const admissions = [];
    const actions = actionsFor(active, admissions);
    for (const descriptor of descriptors) {
      const catalog = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
        (entry) => entry.module_ref === descriptor.moduleRef,
      );
      assert.equal(catalog.contract_digest, descriptor.definition.contractDigest);
      assert.deepEqual(catalog.contract.services.provides, [
        { service: descriptor.service, version: '1.0.0' },
      ]);
      assert.equal(
        profile.entries.find((entry) => entry.entry_id === descriptor.entryId).enabled,
        true,
      );
      const result = await descriptor.call(actions, signal);
      if (descriptor === descriptors[0]) assert.equal(result[0].id, 'skill-1');
      if (descriptor === descriptors[1]) assert.deepEqual(result.versions, []);
      if (descriptor === descriptors[2]) assert.equal(result.skill_id, 'skill-1');
      assert.equal(active.leaseCount, 0, 'operation must release its real generation lease');
    }
    assert.deepEqual(
      requests.map(({ url }) => url.pathname),
      ['/api/v1/skills/', '/api/v1/skills/skill-1/versions', '/api/v1/skills/skill-1/evolution'],
    );
    for (const { url, init } of requests) {
      assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
      assert.equal(init.method, 'GET');
      assert.equal(init.signal, signal);
      assert.equal(
        new Headers(init.headers).get('Authorization'),
        'Bearer skills-loader-trusted-session',
      );
    }
    assert.equal(admissions.length, 3);
    for (let index = 0; index < admissions.length; index += 1) {
      assert.equal(admissions[index].admission.status, 'accepted');
      assert.equal(admissions[index].admission.digest, active.snapshot.digest);
      assert.equal(admissions[index].request.service, descriptors[index].service);
    }
    for (const descriptor of descriptors) {
      const disabled = structuredClone(profile);
      disabled.entries.find((entry) => entry.entry_id === descriptor.entryId).enabled = false;
      const generation = await loader.stage(disabled);
      await manager.publish(generation);
      const disabledAdmissions = [];
      const before = requests.length;
      await assert.rejects(async () =>
        descriptor.call(actionsFor(generation, disabledAdmissions), signal),
      );
      assert.equal(disabledAdmissions.length, 1);
      assert.equal(disabledAdmissions[0].admission.status, 'rejected');
      assert.equal(
        disabledAdmissions[0].admission.reasonCode,
        'desktop_renderer_service_resolve_failed',
      );
      assert.equal(disabledAdmissions[0].admission.runtimeCode, 'missing_service');
      assert.equal(requests.length, before, 'disabled authority must not fall back to HTTP');
      assert.equal(generation.leaseCount, 0, 'failed resolution must release its real lease');
    }
  } finally {
    globalThis.fetch = originalFetch;
    await manager.close();
  }
});
