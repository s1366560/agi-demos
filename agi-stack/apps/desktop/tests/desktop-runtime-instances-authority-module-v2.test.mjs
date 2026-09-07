import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2,
  DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2,
  DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2,
  applyDesktopRuntimeInstancesAuthorityV2,
  desktopRuntimeInstancesAuthorityDefinitionV2,
  desktopRuntimeDeploymentsAuthorityDefinitionV2,
  desktopProjectPlaybooksEventsAuthorityDefinitionV2,
  desktopBackendStoresAuthorityDefinitionV2,
  desktopDeadLetterQueueAuthorityDefinitionV2,
  desktopInstanceTemplatesAuthorityDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopRuntimeInstancesAuthorityModuleV2.js');

const pluginRoot = `${COMPILED_ROOT}/src/plugins`;
const authorityModules = readdirSync(pluginRoot)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${pluginRoot}/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );
const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);

function bootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

test('generated contract declares one credential-free root Runtime Instances Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_RUNTIME_INSTANCES_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap().entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-runtime-instances-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2,
        version: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-fetch');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopRuntimeInstancesAuthorityDefinitionV2.contractDigest);
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
  assert.deepEqual(entry.inject, {});
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization|secret/iu);
  }
});

test('Loader activates the exact Runtime Instances service and disabled Profile fails closed', async () => {
  const loader = new LoaderV2(
    [...createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap());
  const service = generation.resolve(
    DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.throws(
    () =>
      applyDesktopRuntimeInstancesAuthorityV2(
        { provide: () => assert.fail('invalid config must not publish') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_instances_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap());
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-runtime-instances-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_RUNTIME_INSTANCES_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: DESKTOP_RUNTIME_INSTANCES_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );
});
