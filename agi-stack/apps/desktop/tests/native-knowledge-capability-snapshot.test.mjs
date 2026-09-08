import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { config as baseConfig, json } from './nativeKnowledgeProcessingFixtures.mjs';

const require = createRequire(import.meta.url);
const root =
  process.env.AGISTACK_KNOWLEDGE_CAPABILITY_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { loadProjectKnowledgeCapabilities } = require(
  `${root}/src/features/project-knowledge/projectKnowledgeCapabilityAuthority.js`,
);
const { parseDesktopCapabilitySnapshot, desktopCapability } = require(
  `${root}/src/features/runtime/capabilitySnapshot.js`,
);
// Captured from the canonical Electron local acceptance host on 2026-09-08.
const fixture = JSON.parse(
  readFileSync(
    new URL('./fixtures/native-knowledge-local-acceptance-capability.v1.json', import.meta.url),
    'utf8',
  ),
);
const nativeScope = fixture.scope;
const config = {
  ...baseConfig,
  tenantId: nativeScope.tenant_id,
  projectId: nativeScope.project_id,
};
const observed = () => structuredClone(fixture);
const providers = {
  ...fixture.result,
  availability: 'available',
  reason_code: null,
  contract_version: '4.0.0',
  allowed_actions: ['view'],
  scope: { ...fixture.result.scope, project_id: null },
};
const envelope = (entry, name = 'project-project-memories', runtime = 'local_offline') => ({
  version: '5.0.0',
  runtime_state: runtime,
  capabilities: { 'tenant-tenant-providers': providers, [name]: entry },
});
async function project(payload, { actor, scope } = {}) {
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => {
    switch (new URL(url).pathname) {
      case '/api/v1/auth/me':
        return json(actor ?? { user_id: fixture.actor_id, is_active: true });
      case '/api/v1/knowledge/context':
        return json({ contract_version: '1.0.0', scope: scope ?? nativeScope });
      case '/api/v1/knowledge/capabilities':
        return json(payload);
      default:
        throw new Error('unexpected request');
    }
  };
  try {
    return await loadProjectKnowledgeCapabilities({}, config);
  } finally {
    globalThis.fetch = original;
  }
}

for (const runtime of ['local_offline', 'local_online']) {
  test(`native knowledge V1 observation survives the complete ${runtime} snapshot boundary`, async () => {
    const payload = observed();
    const projection = await project(payload);
    const snapshot = parseDesktopCapabilitySnapshot(
      envelope(projection['project-project-memories'], undefined, runtime),
    );
    assert.ok(snapshot);
    assert.deepEqual(snapshot.capabilities['project-project-memories'], payload.result);
    assert.equal(desktopCapability(snapshot, 'project-project-memories').available, true);
    assert.equal(desktopCapability(snapshot, 'tenant-tenant-providers').available, true);
    assert.equal(snapshot.capabilities['project-project-memories'].contract_version, '1.0.0');
    assert.equal(
      snapshot.capabilities['project-project-memories'].reason_code,
      'knowledge_local_acceptance_only',
    );
  });
}
for (const patch of [
  { actor_id: 'foreign' },
  { scope: { ...nativeScope, project_id: 'foreign' } },
  { scope: { ...nativeScope, generation: nativeScope.generation + 1 } },
  { result: { ...observed().result, scope: { ...fixture.result.scope, tenant_id: 'foreign' } } },
  { result: { ...observed().result, allowed_actions: ['unknown-operation'] } },
]) {
  test(`invalid native response stays unavailable without invalidating unrelated capabilities: ${JSON.stringify(patch).slice(0, 75)}`, async () => {
    const projection = await project({ ...observed(), ...patch });
    const snapshot = parseDesktopCapabilitySnapshot(
      envelope(projection['project-project-memories']),
    );
    assert.ok(snapshot);
    assert.equal(desktopCapability(snapshot, 'project-project-memories').available, false);
    assert.equal(snapshot.capabilities['project-project-memories'].provenance, 'declared');
    assert.equal(desktopCapability(snapshot, 'tenant-tenant-providers').available, true);
  });
}
for (const name of ['tenant-tenant-providers', 'project-project-entities', 'search']) {
  test(`unrelated capability ${name} does not acquire native knowledge V1 compatibility`, () => {
    assert.equal(parseDesktopCapabilitySnapshot(envelope(observed().result, name)), null);
  });
}
for (const patch of [
  { contract_version: '1.1.0' },
  { provenance: 'declared' },
  { authority_source: 'cloud_service' },
  { supporting_authority_sources: ['electron'] },
  { allowed_actions: ['invented'] },
  { allowed_actions: ['view', 'view'] },
  { authority_revision: null },
  { scope: { ...fixture.result.scope, project_id: null } },
  { scope: { ...fixture.result.scope, workspace_id: 'workspace' } },
  { extra: true },
]) {
  test(`native V1 adapter rejects malformed or non-native entry: ${JSON.stringify(patch)}`, () => {
    assert.equal(
      parseDesktopCapabilitySnapshot(envelope({ ...observed().result, ...patch })),
      null,
    );
  });
}
test('cloud and legacy snapshots do not acquire native knowledge V1 compatibility', () => {
  assert.equal(
    parseDesktopCapabilitySnapshot(envelope(observed().result, undefined, 'cloud')),
    null,
  );
  assert.equal(
    parseDesktopCapabilitySnapshot({
      version: '4.0.0',
      mode: 'local',
      capabilities: { 'project-project-memories': observed().result },
    }),
    null,
  );
});
