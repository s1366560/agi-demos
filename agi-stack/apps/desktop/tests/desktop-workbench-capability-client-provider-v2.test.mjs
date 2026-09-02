import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkbenchCapabilityClientProviderV2,
  DesktopWorkbenchCapabilityClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/runtime/' +
    'desktopWorkbenchCapabilityClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL(
    '../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);

test('desktop workbench capability client provider fails closed before publication', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkbenchCapabilityClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workbench_capability_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workbench_capability_client_unpublished',
      );
      return true;
    },
  );
});

test('each publication returns one frozen generation-pinned capability client binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const local = provider.publish({
    automationApi: automationApi(),
    config: { ...DEFAULT_CONFIG, mode: 'local', projectId: 'project-local' },
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
  });
  const cloud = provider.publish({
    automationApi: automationApi(),
    config: { ...DEFAULT_CONFIG, mode: 'cloud', projectId: 'project-cloud' },
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
  });

  assert.equal(Object.isFrozen(local), true);
  assert.equal(Object.isFrozen(cloud), true);
  assert.equal(typeof local.client.loadSnapshot, 'function');
  assert.equal(typeof cloud.client.loadSnapshot, 'function');
  assert.notEqual(local, cloud);
  assert.notEqual(local.client, cloud.client);
  assert.equal(provider.resolve(), cloud);
});

test('failed capability client publication keeps the last-good binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const lastGood = provider.publish({
    automationApi: automationApi(),
    config: DEFAULT_CONFIG,
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
  });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get projectId() {
      throw new Error('candidate_capability_config_invalid');
    },
  };

  assert.throws(
    () =>
      provider.publish({
        automationApi: automationApi(),
        config: poisonedConfig,
        pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
      }),
    /candidate_capability_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 workbench capability client', () => {
  assert.match(appSource, /desktopWorkbenchCapabilityClientProviderV2\.publish\(\{/u);
  assert.match(appSource, /automationApi:\s*desktopAutomationApiV2/u);
  assert.match(
    appSource,
    /useDesktopCapabilitySnapshot\(\s*desktopWorkbenchCapabilityClientV2\.client/u,
  );
  assert.doesNotMatch(appSource, /createDesktopWorkbenchCapabilityClient\(/u);
  assert.match(
    providerSource,
    /createDesktopWorkbenchCapabilityClient\(input\.automationApi, config, \{/u,
  );
  assert.match(providerSource, /pluginMarketplaceOperationsV2:\s*input\.pluginMarketplaceOperationsV2/u);
});

function automationApi() {
  return {
    getAutomationCapabilities: async () => ({
      service_version: '0.1.0',
      contract_version: '1.0.0',
      revision: 1,
      supports: { run_now: true, cron_jobs: true },
    }),
  };
}

function pluginMarketplaceOperationsV2() {
  return {
    projectMarketplacePlugins: async (_config, _signal, project) => project([]),
  };
}
