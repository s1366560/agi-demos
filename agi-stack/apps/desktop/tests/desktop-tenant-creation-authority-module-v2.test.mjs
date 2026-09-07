import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const { createDesktopRendererDefinitionsV2, LoaderV2, PLUGIN_MODULE_CATALOG_V2, RuntimeV2Error } = require('@agistack/plugin-runtime');
const authority = require(`${ROOT}/src/plugins/desktopTenantCreationAuthorityModuleV2.js`);
const pluginRoot = `${ROOT}/src/plugins`;
const authorityModules = readdirSync(pluginRoot).filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) => Object.values(require(`${pluginRoot}/${name}`)).filter((value) => value?.moduleRef && typeof value?.apply === 'function'));
const repositoryRoot = new URL('../../../../', import.meta.url);
const bootstrapPath = new URL('shared/profiles/memstack-default-bootstrap.v2.json', repositoryRoot);
const manifestPath = new URL('config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json', repositoryRoot);

test('generated contract and Profile declare one root Tenant Creation Provider', () => {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const module = manifest.modules.find((item) => item.module_ref === authority.DESKTOP_TENANT_CREATION_AUTHORITY_MODULE_REF_V2);
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === authority.DESKTOP_TENANT_CREATION_AUTHORITY_MODULE_REF_V2);
  const entry = bootstrap.entries.find((item) => item.entry_id === 'builtin-desktop-tenant-creation-authority');
  assert.ok(module); assert.ok(catalog); assert.ok(entry);
  assert.deepEqual(module.contract.services.provides, [{ service: authority.DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2, version: authority.DESKTOP_TENANT_CREATION_AUTHORITY_VERSION_V2 }]);
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, authority.desktopTenantCreationAuthorityDefinitionV2.contractDigest);
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-fetch' });
});

test('Loader activates Tenant Creation and disabled Profile fails closed', async () => {
  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new LoaderV2([...createDesktopRendererDefinitionsV2(), ...authorityModules], 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  assert.ok(generation.resolve(authority.DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2, { kind: 'root' }, { version: authority.DESKTOP_TENANT_CREATION_AUTHORITY_VERSION_V2 }));
  const disabled = structuredClone(bootstrap);
  disabled.entries.find((item) => item.entry_id === 'builtin-desktop-tenant-creation-authority').enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(() => disabledGeneration.resolve(authority.DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2, { kind: 'root' }, { version: '1.0.0' }),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service');
  await disabledGeneration.dispose(); await generation.dispose();
});
