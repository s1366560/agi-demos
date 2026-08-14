import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const featureRoot = '/tmp/agistack-desktop-test-dist/src/features/settings-routes';
const {
  createManagementRouteController,
} = require(`${featureRoot}/managementRouteController.js`);
const {
  createProviderRouteClient,
} = require(`${featureRoot}/providerRouteClient.js`);
const {
  createAgentDefinitionsRouteClient,
} = require(`${featureRoot}/agentDefinitionsRouteClient.js`);
const {
  createSkillsRouteClient,
} = require(`${featureRoot}/skillsRouteClient.js`);
const {
  createPluginsRouteClient,
} = require(`${featureRoot}/pluginsRouteClient.js`);
const {
  createMcpServersRouteClient,
} = require(`${featureRoot}/mcpServersRouteClient.js`);
const {
  createProvidersRouteModuleLoader,
} = require(`${featureRoot}/providersRouteModule.js`);
const {
  createAgentDefinitionsRouteModuleLoader,
} = require(`${featureRoot}/agentDefinitionsRouteModule.js`);
const {
  createSkillsRouteModuleLoader,
} = require(`${featureRoot}/skillsRouteModule.js`);
const {
  createPluginsRouteModuleLoader,
} = require(`${featureRoot}/pluginsRouteModule.js`);
const {
  createMcpServersRouteModuleLoader,
} = require(`${featureRoot}/mcpServersRouteModule.js`);
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js'
);
const { DEFAULT_CONFIG } = require(
  '/tmp/agistack-desktop-test-dist/src/types.js'
);

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL(
    '../src/features/navigation/desktopProductionRouteRegistry.ts',
    import.meta.url,
  ),
  'utf8',
);

const ROUTES = [
  {
    id: 'tenant-tenant-providers',
    section: 'models',
    factory: createProvidersRouteModuleLoader,
  },
  {
    id: 'tenant-tenant-agent-definitions',
    section: 'agents',
    factory: createAgentDefinitionsRouteModuleLoader,
  },
  {
    id: 'tenant-tenant-skills',
    section: 'skills',
    factory: createSkillsRouteModuleLoader,
  },
  {
    id: 'tenant-tenant-plugins',
    section: 'plugins',
    factory: createPluginsRouteModuleLoader,
  },
  {
    id: 'tenant-tenant-mcp-servers',
    section: 'mcp',
    factory: createMcpServersRouteModuleLoader,
  },
];

function config(mode = 'cloud') {
  return {
    ...DEFAULT_CONFIG,
    mode,
    apiBaseUrl:
      mode === 'cloud' ? 'https://api.example.test' : 'http://127.0.0.1:8088',
    apiKey: mode === 'cloud' ? 'trusted-cloud-session' : 'local-session-token',
    localApiToken: mode === 'local' ? 'sidecar-launch-capability' : '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
}

test('five stranded settings routes publish real implemented native modules', async () => {
  for (const route of ROUTES) {
    let bindingCalls = 0;
    const loader = route.factory({
      createBinding() {
        bindingCalls += 1;
        return {
          controller: createManagementRouteController({
            capability: route.id,
            client: {
              observe: async (scope) => ({ scope, itemCount: 1 }),
            },
            initialScope: {
              authority: 'cloud',
              tenantId: 'tenant-1',
              projectId: 'project-1',
            },
          }),
          scope: {
            authority: 'cloud',
            tenantId: 'tenant-1',
            projectId: 'project-1',
          },
          Content: () => null,
        };
      },
    });

    assert.equal(bindingCalls, 0, `${route.id} must stay lazy`);
    const module = await loader();
    assert.deepEqual(
      {
        routeId: module.routeId,
        capability: module.capability,
        localPolicy: module.localPolicy,
        disposition: module.disposition,
        availability: module.availability,
        reasonCode: module.reasonCode,
        contentPolicy: module.contentPolicy,
        Surface: typeof module.Surface,
      },
      {
        routeId: route.id,
        capability: route.id,
        localPolicy: 'native_equivalent',
        disposition: 'implemented',
        availability: 'available',
        reasonCode: null,
        contentPolicy: 'route_content',
        Surface: 'function',
      },
    );
  }
});

test('each route owns a typed authority adapter and validates its runtime scope', async () => {
  const scope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const calls = [];
  const cases = [
    [
      createProviderRouteClient(config(), {
        listLlmProviders: async () => {
          calls.push('providers');
          return [{ id: 'provider-1' }];
        },
        listLlmProviderTypes: async () => [],
      }),
      1,
    ],
    [
      createAgentDefinitionsRouteClient(config(), {
        listManagedAgents: async () => {
          calls.push('agents');
          return [{ id: 'agent-1' }, { id: 'agent-2' }];
        },
      }),
      2,
    ],
    [
      createSkillsRouteClient(config(), {
        listManagedSkills: async () => {
          calls.push('skills');
          return [];
        },
      }),
      0,
    ],
    [
      createPluginsRouteClient(config(), {
        listManagedPlugins: async () => {
          calls.push('plugins');
          return [{ id: 'plugin-1' }];
        },
      }),
      1,
    ],
    [
      createMcpServersRouteClient(config(), {
        listMCPServers: async (projectId) => {
          calls.push(`mcp:${projectId}`);
          return [{ id: 'mcp-1' }];
        },
      }),
      1,
    ],
  ];

  for (const [client, itemCount] of cases) {
    assert.deepEqual(await client.observe(scope), { scope, itemCount });
    await assert.rejects(
      client.observe({ ...scope, tenantId: 'tenant-other' }),
      /management_route_runtime_scope_mismatch/,
    );
  }
  assert.deepEqual(calls, [
    'providers',
    'agents',
    'skills',
    'plugins',
    'mcp:project-1',
  ]);
});

test('local provider management observes the sidecar without invoking cloud_request', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const requests = [];
  const cloudInvocations = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command) {
          cloudInvocations.push(command);
          throw new Error('cloud authority must not be used');
        },
      },
    },
  };
  globalThis.fetch = async (input) => {
    requests.push(String(input));
    return new Response('[]', {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const localConfig = { ...config('local'), apiKey: '' };
    const scope = {
      authority: 'local',
      tenantId: localConfig.tenantId,
      projectId: localConfig.projectId,
    };

    assert.deepEqual(await createProviderRouteClient(localConfig).observe(scope), {
      scope,
      itemCount: 0,
    });
    assert.deepEqual(requests.sort(), [
      'http://127.0.0.1:8088/api/v1/llm-providers/?include_inactive=true',
      'http://127.0.0.1:8088/api/v1/llm-providers/types',
    ]);
    assert.deepEqual(cloudInvocations, []);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('controller exposes stable loading, empty, forbidden, unavailable, and retry states', async () => {
  const scope = {
    authority: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  let attempt = 0;
  const controller = createManagementRouteController({
    capability: 'tenant-tenant-skills',
    client: {
      async observe(observedScope) {
        attempt += 1;
        if (attempt === 1) {
          const error = new Error('forbidden');
          error.status = 403;
          throw error;
        }
        if (attempt === 2) return { scope: observedScope, itemCount: 0 };
        return { scope: observedScope, itemCount: 2 };
      },
    },
    initialScope: scope,
  });

  assert.equal(controller.getSnapshot().state, 'loading');
  await controller.load(scope);
  assert.deepEqual(
    {
      state: controller.getSnapshot().state,
      reasonCode: controller.getSnapshot().reasonCode,
      retryVisible: controller.getSnapshot().retryVisible,
    },
    {
      state: 'forbidden',
      reasonCode: 'tenant_tenant_skills_forbidden',
      retryVisible: false,
    },
  );
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'empty');
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().itemCount, 2);
});

test('registry and App bind all five routes without Web escape or DesktopApiClient growth', () => {
  for (const { id } of ROUTES) {
    assert.equal(DESKTOP_IMPLEMENTED_ROUTE_IDS.includes(id), true, id);
    assert.match(registrySource, new RegExp(id.replaceAll('-', '[-]')));
  }
  assert.match(appSource, /createProvidersRouteBindingForRuntime/u);
  assert.match(appSource, /createAgentDefinitionsRouteBindingForRuntime/u);
  assert.match(appSource, /createSkillsRouteBindingForRuntime/u);
  assert.match(appSource, /createPluginsRouteBindingForRuntime/u);
  assert.match(appSource, /createMcpServersRouteBindingForRuntime/u);
  assert.doesNotMatch(
    `${appSource}\n${registrySource}`,
    /settings-routes[\s\S]{0,500}(?:WebView|<webview|<iframe|openExternal|window\.open)/iu,
  );
});
