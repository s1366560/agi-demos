import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { config, projectScope, nativeScope, json } from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const root =
  process.env.AGISTACK_KNOWLEDGE_CAPABILITY_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { loadNativeKnowledgeCapability: load } = require(
  `${root}/src/features/project-knowledge/nativeKnowledgeCapabilityClient.js`,
);
const { loadProjectKnowledgeCapabilities } = require(
  `${root}/src/features/project-knowledge/projectKnowledgeCapabilityAuthority.js`,
);
const { NATIVE_KNOWLEDGE_READ_ACTIONS: reads, NATIVE_KNOWLEDGE_WRITE_ACTIONS: writes } = require(
  `${root}/src/features/project-knowledge/nativeKnowledgeCapabilityActionsGenerated.js`,
);
const fixture = JSON.parse(
  readFileSync(
    new URL('../../../../shared/fixtures/native-knowledge-capabilities.v1.json', import.meta.url),
    'utf8',
  ),
);
const fake = (options = {}) => {
  let actorCalls = 0,
    scopeCalls = 0,
    count = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    count++;
    assert.equal(new URL(String(url)).origin, config.apiBaseUrl);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer identity');
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'launch');
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/auth/me') {
      actorCalls++;
      return json(options.actor?.(actorCalls) ?? { user_id: 'actor', is_active: true });
    }
    if (path === '/api/v1/knowledge/context') {
      scopeCalls++;
      return json({ contract_version: '1.0.0', scope: options.scope?.(scopeCalls) ?? nativeScope });
    }
    assert.equal(path, '/api/v1/knowledge/capabilities');
    options.onCapability?.();
    return options.failure
      ? json({ error: { code: 'failure', message: 'failure' } }, 503)
      : json(options.payload ?? fixture);
  };
  return {
    restore: () => {
      globalThis.fetch = original;
    },
    count: () => count,
  };
};
const closed = (entry) => {
  assert.equal(entry.availability, 'unavailable');
  assert.equal(entry.provenance, 'declared');
  assert.deepEqual(entry.allowed_actions, []);
};

test('closed release is observed from authenticated scoped endpoint without pretending it is available', async () => {
  const f = fake();
  try {
    const entry = await load(config, projectScope);
    assert.deepEqual(entry, fixture.result);
    assert.equal(f.count(), 5);
    assert.ok(Object.isFrozen(entry));
  } finally {
    f.restore();
  }
});
test('both legacy and processing actions survive the existing memory capability producer', async () => {
  assert.equal(new Set([...reads, ...writes]).size, 53);
  assert.ok(reads.includes('sync_status'));
  for (const action of ['failed_processing', 'failed_index', 'processing_audits',
    'community_active', 'community_builds', 'community_build', 'community_audit', 'graph_source'])
    assert.ok(reads.includes(action));
  assert.ok(writes.includes('sync_link'));
  for (const action of ['create_community_build', 'select_community_build',
    'process_community_one', 'retry_community', 'activate_community_build'])
    assert.ok(writes.includes(action));
  const payload = structuredClone(fixture);
  payload.result = {
    ...payload.result,
    availability: 'degraded',
    reason_code: 'desktop_project_memories_actions_partial',
    allowed_actions: [...reads, ...writes].sort(),
  };
  const f = fake({ payload });
  try {
    const projection = await loadProjectKnowledgeCapabilities({}, config);
    assert.deepEqual(projection['project-project-memories'], payload.result);
    assert.equal(projection['project-project-team'].availability, 'unavailable');
  } finally {
    f.restore();
  }
});
for (const field of [
  'tenant_id',
  'project_id',
  'context_revision',
  'profile_id',
  'generation',
  'digest',
])
  test(`late observed ${field} mismatch stays declared unavailable`, async () => {
    const f = fake({
      scope: (call) =>
        call === 1
          ? nativeScope
          : {
              ...nativeScope,
              [field]: typeof nativeScope[field] === 'number' ? nativeScope[field] + 1 : 'foreign',
            },
    });
    try {
      closed(await load(config, projectScope));
    } finally {
      f.restore();
    }
  });
for (const patch of [
  { actor_id: 'foreign' },
  { scope: { ...nativeScope, generation: 2 } },
  { extra: true },
  { result: { ...fixture.result, allowed_actions: ['index_one'] } },
  { result: { ...fixture.result, authority_revision: 2 } },
  { result: { ...fixture.result, provenance: 'declared' } },
  { result: { ...fixture.result, authority_source: 'cloud_service' } },
  { result: { ...fixture.result, scope: { ...fixture.result.scope, project_id: 'foreign' } } },
  { result: { ...fixture.result, extra: true } },
  {
    result: {
      ...fixture.result,
      availability: 'available',
      reason_code: null,
      allowed_actions: ['unknown-operation'],
    },
  },
])
  test(`malformed or mismatched entry is never published observed ${JSON.stringify(patch).slice(0, 75)}`, async () => {
    const f = fake({ payload: { ...fixture, ...patch } });
    try {
      closed(await load(config, projectScope));
    } finally {
      f.restore();
    }
  });
test('actor switch, inactive actor and failed reads cannot become observed', async () => {
  for (const options of [
    { actor: (call) => ({ user_id: call === 1 ? 'actor' : 'other', is_active: true }) },
    { actor: () => ({ user_id: 'actor', is_active: false }) },
    { failure: true },
  ]) {
    const f = fake(options);
    try {
      closed(await load(config, projectScope));
    } finally {
      f.restore();
    }
  }
});
test('cancellation after capability response is propagated, not converted to a fallback', async () => {
  const abort = new AbortController();
  const f = fake({ onCapability: () => abort.abort() });
  try {
    await assert.rejects(load(config, projectScope, abort.signal), (e) => e.name === 'AbortError');
    assert.equal(f.count(), 3);
  } finally {
    f.restore();
  }
});
test('nonlocal transport is never probed', async () => {
  const f = fake();
  try {
    closed(await load({ ...config, apiBaseUrl: 'https://cloud.test' }, projectScope));
    assert.equal(f.count(), 0);
  } finally {
    f.restore();
  }
});
