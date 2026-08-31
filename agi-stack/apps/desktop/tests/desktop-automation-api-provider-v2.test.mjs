import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopAutomationApiProviderV2,
  DesktopAutomationApiProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/automations/' +
    'desktopAutomationApiProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL(
    '../src/features/automations/desktopAutomationApiProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);

test('desktop automation API provider fails closed before publication', () => {
  const provider = createDesktopAutomationApiProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopAutomationApiProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_automation_api_unpublished');
      assert.equal(error.message, 'desktop_automation_api_unpublished');
      return true;
    },
  );
});

test('each publication returns one frozen generation-pinned automation API binding', async () => {
  const provider = createDesktopAutomationApiProviderV2();
  const calls = [];
  const localConfig = {
    ...DEFAULT_CONFIG,
    mode: 'local',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
  const local = provider.publish({
    baseApi: baseApi(calls, 'local'),
    config: localConfig,
  });
  localConfig.workspaceId = 'workspace-mutated';
  const cloud = provider.publish({
    baseApi: baseApi(calls, 'cloud'),
    config: {
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      projectId: 'project-2',
      workspaceId: 'workspace-2',
    },
  });

  await local.api.createAutomation(automationInput('local-create'), 'project-1');
  await cloud.api.createAutomation(automationInput('cloud-create'), 'project-2');

  assert.equal(Object.isFrozen(local), true);
  assert.equal(Object.isFrozen(cloud), true);
  assert.notEqual(local, cloud);
  assert.equal(provider.resolve(), cloud);
  assert.deepEqual(calls, [
    {
      authority: 'local',
      input: { ...automationInput('local-create'), workspace_id: 'workspace-1' },
      projectId: 'project-1',
    },
    {
      authority: 'cloud',
      input: automationInput('cloud-create'),
      projectId: 'project-2',
    },
  ]);
});

test('failed automation API publication keeps the last-good binding', () => {
  const provider = createDesktopAutomationApiProviderV2();
  const lastGood = provider.publish({
    baseApi: baseApi([], 'last-good'),
    config: DEFAULT_CONFIG,
  });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get workspaceId() {
      throw new Error('candidate_automation_config_invalid');
    },
  };

  assert.throws(
    () =>
      provider.publish({
        baseApi: baseApi([], 'candidate'),
        config: poisonedConfig,
      }),
    /candidate_automation_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 automation API without constructing it directly', () => {
  assert.match(appSource, /desktopAutomationApiProviderV2\.publish\(\{/u);
  assert.match(appSource, /baseApi:\s*api/u);
  assert.match(appSource, /createDesktopWorkbenchCapabilityClient\(desktopAutomationApiV2\.api/u);
  assert.match(appSource, /api:\s*desktopAutomationApiV2\.api/u);
  assert.doesNotMatch(appSource, /createDesktopAutomationApi\(/u);
  assert.match(providerSource, /createDesktopAutomationApi\(input\.baseApi, config\)/u);
});

function baseApi(calls, authority) {
  return {
    createAutomation: async (input, projectId) => {
      calls.push({ authority, input, projectId });
      return { ...input, id: `${authority}-automation`, project_id: projectId };
    },
  };
}

function automationInput(idempotencyKey) {
  return {
    idempotency_key: idempotencyKey,
    name: 'Scoped automation',
    schedule: { kind: 'every', config: { interval_seconds: 60 } },
    payload: { kind: 'agent_turn', config: { message: 'Run it' } },
  };
}
