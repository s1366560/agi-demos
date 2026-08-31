import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { after, before, test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopAgentAuthorityProviderV2,
  DesktopAgentAuthorityProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/agent-authority/' +
    'desktopAgentAuthorityProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL(
    '../src/features/agent-authority/desktopAgentAuthorityProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const previousLocalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

before(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: memoryStorage(),
  });
});

after(() => {
  if (previousLocalStorage) {
    Object.defineProperty(globalThis, 'localStorage', previousLocalStorage);
    return;
  }
  delete globalThis.localStorage;
});

test('desktop agent authority provider fails closed before publication', () => {
  const provider = createDesktopAgentAuthorityProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopAgentAuthorityProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_agent_authority_unpublished');
      assert.equal(error.message, 'desktop_agent_authority_unpublished');
      return true;
    },
  );
});

test('publications pin local and cloud authority to immutable generation scope', () => {
  const provider = createDesktopAgentAuthorityProviderV2();
  const localConfig = {
    ...DEFAULT_CONFIG,
    mode: 'local',
    tenantId: 'tenant-local',
    projectId: 'project-local',
  };
  const local = provider.publish({ config: localConfig, principalId: 'ignored-local-user' });
  localConfig.projectId = 'project-mutated';
  const cloud = provider.publish({
    config: {
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      tenantId: 'tenant-cloud',
      projectId: 'project-cloud',
    },
    principalId: 'user-cloud',
  });

  assert.equal(Object.isFrozen(local), true);
  assert.equal(Object.isFrozen(cloud), true);
  assert.equal(local.adapter.authority, 'local');
  assert.deepEqual(local.adapter.allowedActions, ['read_activity', 'write_activity']);
  assert.equal(local.cloudScope, undefined);
  assert.equal(local.adapter.activityScope.projectId, 'project-local');
  assert.equal(cloud.adapter.authority, 'cloud');
  assert.deepEqual(cloud.cloudScope, {
    authority: 'cloud',
    principalId: 'user-cloud',
    tenantId: 'tenant-cloud',
    projectId: 'project-cloud',
  });
  assert.equal(Object.isFrozen(cloud.cloudScope), true);
  assert.notEqual(local, cloud);
  assert.equal(provider.resolve(), cloud);
});

test('cloud authority stays unscoped until principal and project scope are complete', () => {
  const provider = createDesktopAgentAuthorityProviderV2();
  const binding = provider.publish({
    config: { ...DEFAULT_CONFIG, mode: 'cloud', projectId: '' },
    principalId: null,
  });

  assert.equal(binding.adapter.authority, 'cloud');
  assert.equal(binding.cloudScope, undefined);
});

test('failed agent authority publication keeps the last-good binding', () => {
  const provider = createDesktopAgentAuthorityProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG, principalId: null });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get projectId() {
      throw new Error('candidate_agent_authority_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig, principalId: 'user-candidate' }),
    /candidate_agent_authority_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 agent authority binding', () => {
  assert.match(appSource, /desktopAgentAuthorityProviderV2\.publish\(\{/u);
  assert.match(appSource, /principalId:\s*auth\.user\?\.user_id/u);
  assert.match(appSource, /adapter:\s*activityAuthorityAdapter/u);
  assert.match(appSource, /cloudScope:\s*activityAuthorityScope/u);
  assert.doesNotMatch(appSource, /createDesktopAgentAuthorityAdapter\(/u);
  assert.match(providerSource, /createDesktopAgentAuthorityAdapter\(config\)/u);
});

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}
