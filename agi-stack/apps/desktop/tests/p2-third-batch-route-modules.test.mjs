import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src/features/settings-routes';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');

const { createEvolutionRouteClient } = require(`${root}/evolutionRouteClient.js`);
const { createEvolutionRouteController } = require(`${root}/evolutionRouteController.js`);
const { createEvolutionRouteModuleLoader } = require(`${root}/evolutionRouteModule.js`);
const { createChannelsRouteClient } = require(`${root}/channelsRouteClient.js`);
const { createChannelsRouteController } = require(`${root}/channelsRouteController.js`);
const { createChannelsRouteModuleLoader } = require(`${root}/channelsRouteModule.js`);
const { createTemplatesRouteClient } = require(`${root}/templatesRouteClient.js`);
const { createTemplatesRouteController } = require(`${root}/templatesRouteController.js`);
const { createTemplatesRouteModuleLoader } = require(`${root}/templatesRouteModule.js`);
const { createProfileRouteClient } = require(`${root}/profileRouteClient.js`);
const { createProfileRouteController } = require(`${root}/profileRouteController.js`);
const { createProfileRouteModuleLoader } = require(`${root}/profileRouteModule.js`);
const { EvolutionRoutePage } = require(`${root}/EvolutionRoutePage.js`);
const { ChannelsRoutePage } = require(`${root}/ChannelsRoutePage.js`);
const { TemplatesRoutePage } = require(`${root}/TemplatesRoutePage.js`);
const { ProfileRoutePage } = require(`${root}/ProfileRoutePage.js`);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});

const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch',
  mode: 'local',
});

test('P2 third-batch route modules are lazy native implementations with exact identities', async () => {
  const cases = [
    ['tenant-tenant-evolution', 'native_equivalent', createEvolutionRouteModuleLoader],
    ['project-project-channels', 'native_equivalent', createChannelsRouteModuleLoader],
    ['tenant-tenant-templates', 'native_equivalent', createTemplatesRouteModuleLoader],
    ['user-profile', 'native_equivalent', createProfileRouteModuleLoader],
  ];
  for (const [routeId, localPolicy, factory] of cases) {
    let bindings = 0;
    const module = await factory({
      createBinding() {
        bindings += 1;
        throw new Error('binding must remain render-lazy');
      },
    })();
    assert.equal(bindings, 0);
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
        routeId,
        capability: routeId,
        localPolicy,
        disposition: 'implemented',
        availability: 'available',
        reasonCode: null,
        contentPolicy: 'route_content',
        Surface: 'function',
      },
    );
  }
});

test('Evolution client uses Cloud trusted-session actions and Local sidecar reason authority', async () => {
  const requests = [];
  const restore = mockFetch(requests, [
    evolutionOverview(),
    evolutionConfig(),
    { tenant_id: 'tenant-1', result: {} },
    evolutionConfig({ enabled: false }),
    evolutionJob({ status: 'applied' }),
    evolutionJob({ status: 'rejected' }),
  ]);
  try {
    const scope = { authority: 'cloud', tenantId: 'tenant-1' };
    const client = createEvolutionRouteClient(cloudConfig);
    const observed = await client.observe(scope);
    assert.equal(observed.itemCount, 1);
    assert.deepEqual(observed.allowedActions, [
      'view',
      'configure',
      'run',
      'apply-job',
      'reject-job',
    ]);
    await client.run(scope);
    await client.updateConfig(scope, { enabled: false });
    await client.reviewJob(scope, 'job-1', 'apply');
    await client.reviewJob(scope, 'job-1', 'reject');
  } finally {
    restore();
  }
  assert.deepEqual(
    requests.map((request) => [new URL(request.url).pathname, request.init.method ?? 'GET']),
    [
      ['/api/v1/skills/evolution/overview', 'GET'],
      ['/api/v1/skills/evolution/config', 'GET'],
      ['/api/v1/skills/evolution/run', 'POST'],
      ['/api/v1/skills/evolution/config', 'PUT'],
      ['/api/v1/skills/evolution/jobs/job-1/apply', 'POST'],
      ['/api/v1/skills/evolution/jobs/job-1/reject', 'POST'],
    ],
  );
  assertAuthorityHeaders(requests, 'trusted-session', null);

  const localRequests = [];
  const restoreLocal = mockFetch(localRequests, [
    errorPayload(501, 'local_skill_evolution_authority_unavailable'),
  ]);
  try {
    await assert.rejects(
      createEvolutionRouteClient(localConfig).observe({
        authority: 'local',
        tenantId: 'tenant-1',
      }),
      (error) =>
        error.status === 501 &&
        error.reasonCode === 'local_skill_evolution_authority_unavailable',
    );
  } finally {
    restoreLocal();
  }
  assert.equal(new URL(localRequests[0].url).pathname, '/api/v1/skills/evolution/overview');
  assertAuthorityHeaders(localRequests, 'local-session', 'private-launch');
});

test('Channels client exposes project CRUD/test authority and fails closed in Local mode', async () => {
  const requests = [];
  const restore = mockFetch(requests, [
    { items: [channelCatalog()] },
    { items: [channelConfig()] },
    channelConfig({ id: 'channel-2' }),
    channelConfig({ enabled: false }),
    { success: true, message: 'ok' },
    null,
  ]);
  try {
    const scope = {
      authority: 'cloud',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    };
    const client = createChannelsRouteClient(cloudConfig);
    const observed = await client.observe(scope);
    assert.equal(observed.itemCount, 1);
    assert.equal(observed.catalog.length, 1);
    await client.create(scope, {
      channel_type: 'feishu',
      name: 'Ops',
      enabled: true,
    });
    await client.update(scope, 'channel-1', { enabled: false });
    await client.test(scope, 'channel-1');
    await client.remove(scope, 'channel-1');
  } finally {
    restore();
  }
  assert.deepEqual(
    requests.map((request) => [new URL(request.url).pathname, request.init.method ?? 'GET']),
    [
      ['/api/v1/channels/tenants/tenant-1/plugins/channel-catalog', 'GET'],
      ['/api/v1/channels/projects/project-1/configs', 'GET'],
      ['/api/v1/channels/projects/project-1/configs', 'POST'],
      ['/api/v1/channels/configs/channel-1', 'PUT'],
      ['/api/v1/channels/configs/channel-1/test', 'POST'],
      ['/api/v1/channels/configs/channel-1', 'DELETE'],
    ],
  );
  assertAuthorityHeaders(requests, 'trusted-session', null);

  const localRequests = [];
  const restoreLocal = mockFetch(localRequests, [
    errorPayload(501, 'local_channel_runtime_not_applicable'),
  ]);
  try {
    await assert.rejects(
      createChannelsRouteClient(localConfig).observe({
        authority: 'local',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      }),
      (error) =>
        error.status === 501 && error.reasonCode === 'local_channel_runtime_not_applicable',
    );
  } finally {
    restoreLocal();
  }
  assertAuthorityHeaders(localRequests, 'local-session', 'private-launch');
});

test('Templates client owns list, categories, detail, install, and seed contracts', async () => {
  const requests = [];
  const restore = mockFetch(requests, [
    { templates: [templateSummary()], total: 1 },
    { categories: ['coding'] },
    templateDetail(),
    { id: 'agent-1', name: 'installed', display_name: 'Installed' },
    { created: 2, message: 'Seeded 2 builtin templates' },
  ]);
  try {
    const scope = { authority: 'cloud', tenantId: 'tenant-1' };
    const client = createTemplatesRouteClient(cloudConfig);
    const observed = await client.observe(scope, {
      page: 1,
      pageSize: 12,
      search: 'code',
    });
    assert.equal(observed.itemCount, 1);
    assert.deepEqual(observed.categories, ['coding']);
    assert.equal((await client.get(scope, 'template-1')).id, 'template-1');
    await client.install(scope, 'template-1');
    assert.equal(await client.seed(scope), 2);
  } finally {
    restore();
  }
  assert.deepEqual(
    requests.map((request) => [new URL(request.url).pathname, request.init.method ?? 'GET']),
    [
      ['/api/v1/subagents/templates/list', 'GET'],
      ['/api/v1/subagents/templates/categories', 'GET'],
      ['/api/v1/subagents/templates/template-1', 'GET'],
      ['/api/v1/subagents/templates/template-1/install', 'POST'],
      ['/api/v1/subagents/templates/seed', 'POST'],
    ],
  );
  assertAuthorityHeaders(requests, 'trusted-session', null);

  const localRequests = [];
  const restoreLocal = mockFetch(localRequests, [
    errorPayload(501, 'local_subagent_registry_unavailable'),
  ]);
  try {
    await assert.rejects(
      createTemplatesRouteClient(localConfig).observe({
        authority: 'local',
        tenantId: 'tenant-1',
      }),
      (error) => error.status === 501 && error.reasonCode === 'local_subagent_registry_unavailable',
    );
  } finally {
    restoreLocal();
  }
  assert.equal(localRequests.length, 1);
  assert.equal(new URL(localRequests[0].url).pathname, '/api/v1/subagents/templates/list');
  assertAuthorityHeaders(localRequests, 'local-session', 'private-launch');
});

test('Profile client is Cloud editable and Local observed read-only with stable mutation reason', async () => {
  const requests = [];
  const restore = mockFetch(requests, [
    currentUser(),
    currentUser({ name: 'Updated' }),
    { success: true, message: 'changed' },
  ]);
  try {
    const scope = { authority: 'cloud' };
    const client = createProfileRouteClient(cloudConfig);
    const observed = await client.observe(scope);
    assert.equal(observed.user.email, 'user@example.test');
    assert.deepEqual(observed.allowedActions, [
      'view',
      'update',
      'change-language',
      'change-password',
    ]);
    await client.update(scope, {
      name: 'Updated',
      preferred_language: 'en-US',
    });
    await client.changePassword(scope, {
      oldPassword: 'old-pass',
      newPassword: 'new-pass',
    });
  } finally {
    restore();
  }
  assert.deepEqual(
    requests.map((request) => [new URL(request.url).pathname, request.init.method ?? 'GET']),
    [
      ['/api/v1/auth/me', 'GET'],
      ['/api/v1/users/me', 'PUT'],
      ['/api/v1/auth/force-change-password', 'POST'],
    ],
  );
  assertAuthorityHeaders(requests, 'trusted-session', null);

  const localRequests = [];
  const restoreLocal = mockFetch(localRequests, [currentUser({ user_id: 'local-user' })]);
  try {
    const client = createProfileRouteClient(localConfig);
    const scope = { authority: 'local' };
    const observed = await client.observe(scope);
    assert.equal(observed.availability, 'degraded');
    assert.equal(observed.reasonCode, 'local_profile_mutation_authority_unavailable');
    assert.deepEqual(observed.allowedActions, ['view']);
    await assert.rejects(
      client.update(scope, { name: 'Blocked' }),
      (error) =>
        error.status === 501 && error.reasonCode === 'local_profile_mutation_authority_unavailable',
    );
    await assert.rejects(
      client.changePassword(scope, {
        oldPassword: 'old-pass',
        newPassword: 'new-pass',
      }),
      (error) =>
        error.status === 501 && error.reasonCode === 'local_profile_mutation_authority_unavailable',
    );
  } finally {
    restoreLocal();
  }
  assert.equal(localRequests.length, 1);
  assertAuthorityHeaders(localRequests, 'local-session', 'private-launch');
});

test('third-batch controllers reject stale scopes and preserve stable reason codes', async () => {
  const evolutionScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const evolution = createEvolutionRouteController({
    client: { observe: async (scope) => evolutionObservation(scope) },
    initialScope: evolutionScope,
  });
  await evolution.load(evolutionScope);
  assert.equal(evolution.getSnapshot().state, 'ready');

  const channelsScope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const channels = createChannelsRouteController({
    client: { observe: async (scope) => channelsObservation(scope) },
    initialScope: channelsScope,
  });
  await channels.load(channelsScope);
  assert.equal(channels.getSnapshot().state, 'empty');

  const templatesScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const templates = createTemplatesRouteController({
    client: { observe: async (scope) => templatesObservation(scope) },
    initialScope: templatesScope,
  });
  await templates.load(templatesScope);
  assert.equal(templates.getSnapshot().state, 'ready');

  const forbidden = Object.assign(new Error('forbidden'), {
    status: 403,
    reasonCode: 'user_profile_forbidden',
  });
  const profile = createProfileRouteController({
    client: { observe: async () => Promise.reject(forbidden) },
    initialScope: { authority: 'cloud' },
  });
  await profile.load({ authority: 'cloud' });
  assert.equal(profile.getSnapshot().state, 'forbidden');
  assert.equal(profile.getSnapshot().reasonCode, 'user_profile_forbidden');
  assert.equal(profile.getSnapshot().retryVisible, false);

  let completeStale;
  const staleObservation = new Promise((resolve) => {
    completeStale = resolve;
  });
  const scopeOne = { authority: 'cloud', tenantId: 'tenant-1' };
  const scopeTwo = { authority: 'cloud', tenantId: 'tenant-2' };
  const staleSafe = createEvolutionRouteController({
    client: {
      observe: (scope) =>
        scope.tenantId === 'tenant-1'
          ? staleObservation
          : Promise.resolve(evolutionObservation(scope)),
    },
    initialScope: scopeOne,
  });
  const firstLoad = staleSafe.load(scopeOne);
  await staleSafe.load(scopeTwo);
  completeStale(evolutionObservation(scopeOne));
  await firstLoad;
  assert.equal(staleSafe.getSnapshot().scope.tenantId, 'tenant-2');
  assert.equal(staleSafe.getSnapshot().state, 'ready');
});

test('native route errors never promote localized detail text into reason codes', async () => {
  const requests = [];
  const restore = mockFetch(requests, [
    {
      __error: true,
      status: 403,
      payload: { detail: 'Localized human message' },
    },
  ]);
  try {
    await assert.rejects(
      createProfileRouteClient(cloudConfig).observe({ authority: 'cloud' }),
      (error) => error.status === 403 && error.reasonCode === 'desktop_native_route_http_403',
    );
  } finally {
    restore();
  }
});

test('third-batch controllers expose every declared Cloud action through typed operations', async () => {
  const calls = [];
  const evolutionScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const evolution = createEvolutionRouteController({
    client: {
      observe: async (scope) => evolutionObservation(scope),
      run: async () => calls.push('evolution:run'),
      updateConfig: async (_scope, input) => {
        calls.push(`evolution:configure:${String(input.enabled)}`);
        return evolutionConfig(input);
      },
      reviewJob: async (_scope, id, action) => calls.push(`evolution:${action}:${id}`),
    },
    initialScope: evolutionScope,
  });
  await evolution.load(evolutionScope);
  await evolution.run(evolutionScope);
  await evolution.updateConfig(evolutionScope, { enabled: false });
  await evolution.reviewJob(evolutionScope, 'job-1', 'apply');
  await evolution.reviewJob(evolutionScope, 'job-1', 'reject');

  const channelsScope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const channels = createChannelsRouteController({
    client: {
      observe: async (scope) => channelsObservation(scope),
      getSchema: async () => {
        calls.push('channels:schema');
        return channelSchema();
      },
      create: async () => {
        calls.push('channels:create');
        return channelConfig();
      },
      update: async () => {
        calls.push('channels:update');
        return channelConfig();
      },
      test: async () => {
        calls.push('channels:test');
        return { success: true, message: 'ok' };
      },
      remove: async () => calls.push('channels:delete'),
    },
    initialScope: channelsScope,
  });
  await channels.load(channelsScope);
  await channels.getSchema(channelsScope, 'feishu');
  await channels.create(channelsScope, { channel_type: 'feishu', name: 'Ops' });
  await channels.update(channelsScope, 'channel-1', { enabled: false });
  await channels.test(channelsScope, 'channel-1');
  await channels.remove(channelsScope, 'channel-1');

  const templatesScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const templates = createTemplatesRouteController({
    client: {
      observe: async (scope) => templatesObservation(scope),
      get: async () => {
        calls.push('templates:detail');
        return templateDetail();
      },
      install: async () => calls.push('templates:install'),
      seed: async () => {
        calls.push('templates:seed');
        return 2;
      },
    },
    initialScope: templatesScope,
  });
  await templates.load(templatesScope);
  await templates.filter(templatesScope, { search: 'code', category: 'coding' });
  await templates.get(templatesScope, 'template-1');
  await templates.install(templatesScope, 'template-1');
  assert.equal(await templates.seed(templatesScope), 2);

  const profileScope = { authority: 'cloud' };
  const profile = createProfileRouteController({
    client: {
      observe: async () => profileObservation(profileScope),
      update: async (_scope, input) => {
        calls.push(`profile:update:${input.preferred_language}`);
        return currentUser(input);
      },
      changePassword: async () => calls.push('profile:change-password'),
    },
    initialScope: profileScope,
  });
  await profile.load(profileScope);
  await profile.update(profileScope, { name: 'Updated', preferred_language: 'zh-CN' });
  await profile.changePassword(profileScope, {
    oldPassword: 'old-password',
    newPassword: 'new-password',
  });

  assert.deepEqual(calls, [
    'evolution:run',
    'evolution:configure:false',
    'evolution:apply:job-1',
    'evolution:reject:job-1',
    'channels:schema',
    'channels:create',
    'channels:update',
    'channels:test',
    'channels:delete',
    'templates:detail',
    'templates:install',
    'templates:seed',
    'profile:update:zh-CN',
    'profile:change-password',
  ]);
});

test('native Content pages render controls for their safely declared actions', async () => {
  const evolutionScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const evolution = completeEvolutionController(evolutionScope);
  await evolution.load(evolutionScope);
  const evolutionMarkup = renderRoute(
    React.createElement(EvolutionRoutePage, {
      model: evolution.getSnapshot(),
      controller: evolution,
    }),
  );
  assertActions(evolutionMarkup, ['run', 'configure', 'apply-job', 'reject-job']);

  const channelsScope = {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const channels = completeChannelsController(channelsScope);
  await channels.load(channelsScope);
  const channelsMarkup = renderRoute(
    React.createElement(ChannelsRoutePage, {
      model: channels.getSnapshot(),
      controller: channels,
    }),
  );
  assertActions(channelsMarkup, [
    'view-channel-catalog',
    'view-channel-schema',
    'list-channel-configs',
    'create-channel-config',
    'update-channel-config',
    'delete-channel-config',
    'test-channel-config',
  ]);

  const templatesScope = { authority: 'cloud', tenantId: 'tenant-1' };
  const templates = completeTemplatesController(templatesScope);
  await templates.load(templatesScope);
  const templatesMarkup = renderRoute(
    React.createElement(TemplatesRoutePage, {
      model: templates.getSnapshot(),
      controller: templates,
    }),
  );
  assertActions(templatesMarkup, [
    'list',
    'search',
    'filter',
    'view-detail',
    'install',
    'seed',
    'retry',
  ]);

  const profileScope = { authority: 'cloud' };
  const profile = completeProfileController(profileScope, profileObservation(profileScope));
  await profile.load(profileScope);
  const profileMarkup = renderRoute(
    React.createElement(ProfileRoutePage, {
      model: profile.getSnapshot(),
      controller: profile,
    }),
  );
  assertActions(profileMarkup, ['update', 'change-language', 'change-password']);

  const localScope = { authority: 'local' };
  const localProfile = completeProfileController(localScope, profileObservation(localScope, true));
  await localProfile.load(localScope);
  const localMarkup = renderRoute(
    React.createElement(ProfileRoutePage, {
      model: localProfile.getSnapshot(),
      controller: localProfile,
    }),
  );
  assert.match(
    localMarkup,
    /data-reason-code="local_profile_mutation_authority_unavailable"/u,
  );
  assert.match(
    localMarkup,
    /The required service or authority is currently unavailable\./u,
  );
  assert.doesNotMatch(
    localMarkup,
    /<code[^>]*>local_profile_mutation_authority_unavailable<\/code>/u,
  );
  assert.match(localMarkup, /data-action="change-password"[\s\S]*disabled=""/u);
});

function mockFetch(requests, payloads) {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const next = payloads.shift();
    if (next?.__error) return response(next.payload, next.status);
    return response(next, init.method === 'DELETE' ? 204 : 200);
  };
  return () => {
    globalThis.fetch = original;
  };
}

function response(payload, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: status === 204 ? {} : { 'content-type': 'application/json' },
  });
}

function errorPayload(status, reasonCode) {
  return { __error: true, status, payload: { reason_code: reasonCode } };
}

function assertAuthorityHeaders(requests, credential, launch) {
  for (const request of requests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), `Bearer ${credential}`);
    assert.equal(headers.get('X-Agistack-Launch'), launch);
    assert.equal(request.init.credentials, 'omit');
  }
}

function evolutionConfig(overrides = {}) {
  return {
    enabled: true,
    min_sessions_per_skill: 3,
    scoring_min_sessions_per_skill: 2,
    min_avg_score: 0.75,
    max_sessions_per_batch: 20,
    evolution_interval_minutes: 30,
    publish_mode: 'review',
    auto_apply: false,
    ...overrides,
  };
}

function evolutionJob(overrides = {}) {
  return {
    id: 'job-1',
    project_id: null,
    skill_name: 'coding',
    action: 'replace',
    status: 'pending_review',
    rationale: null,
    candidate_preview: null,
    blocked_by_review: true,
    created_at: '2026-08-05T00:00:00Z',
    ...overrides,
  };
}

function evolutionOverview() {
  return {
    stats: { total_sessions: 1, pending_jobs: 1, total_jobs: 1 },
    skills: [{ skill_id: 'skill-1', skill_name: 'coding', session_count: 1 }],
    recent_sessions: [],
    recent_jobs: [evolutionJob()],
    trigger: { enabled: true },
  };
}

function evolutionObservation(scope) {
  return {
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view'],
    itemCount: 1,
    overview: evolutionOverview(),
    config: evolutionConfig(),
  };
}

function channelCatalog() {
  return {
    channel_type: 'feishu',
    plugin_name: 'feishu',
    enabled: true,
    discovered: true,
  };
}

function channelConfig(overrides = {}) {
  return {
    id: 'channel-1',
    project_id: 'project-1',
    channel_type: 'feishu',
    name: 'Ops',
    enabled: true,
    status: 'connected',
    ...overrides,
  };
}

function channelsObservation(scope) {
  return {
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view'],
    itemCount: 0,
    catalog: [],
    configs: [],
  };
}

function templateSummary() {
  return {
    id: 'template-1',
    tenant_id: 'tenant-1',
    name: 'coding',
    version: '1.0.0',
    display_name: 'Coding',
    description: 'Coding helper',
    category: 'coding',
    tags: [],
    author: 'MemStack',
    is_builtin: true,
    is_published: true,
    install_count: 1,
    rating: 5,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function templateDetail() {
  return {
    ...templateSummary(),
    system_prompt: 'safe prompt',
    trigger_description: '',
    trigger_keywords: [],
    trigger_examples: [],
    model: 'default',
    max_tokens: 1000,
    temperature: 0,
    max_iterations: 5,
    allowed_tools: [],
    metadata: null,
  };
}

function templatesObservation(scope) {
  return {
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view'],
    itemCount: 1,
    templates: [templateSummary()],
    categories: ['coding'],
    total: 1,
    page: 1,
    pageSize: 12,
  };
}

function currentUser(overrides = {}) {
  return {
    user_id: 'user-1',
    email: 'user@example.test',
    name: 'User',
    roles: ['user'],
    global_roles: [],
    is_active: true,
    is_superuser: false,
    created_at: '2026-08-05T00:00:00Z',
    profile: {},
    preferred_language: 'en-US',
    ...overrides,
  };
}

function channelSchema() {
  return {
    channel_type: 'feishu',
    plugin_name: 'feishu',
    source: 'entrypoint',
    schema_supported: true,
    config_schema: { type: 'object', properties: {}, required: [] },
    config_ui_hints: {},
    defaults: {},
    secret_paths: [],
  };
}

function profileObservation(scope, local = false) {
  return {
    scope,
    authority: scope.authority,
    availability: local ? 'degraded' : 'available',
    reasonCode: local ? 'local_profile_mutation_authority_unavailable' : null,
    allowedActions: local ? ['view'] : ['view', 'update', 'change-language', 'change-password'],
    itemCount: 1,
    user: currentUser({ user_id: local ? 'local-user' : 'user-1' }),
  };
}

function completeEvolutionController(scope) {
  return createEvolutionRouteController({
    client: {
      observe: async (nextScope) => ({
        ...evolutionObservation(nextScope),
        allowedActions: ['view', 'configure', 'run', 'apply-job', 'reject-job'],
      }),
      run: async () => {},
      updateConfig: async (_scope, input) => evolutionConfig(input),
      reviewJob: async () => {},
    },
    initialScope: scope,
  });
}

function completeChannelsController(scope) {
  return createChannelsRouteController({
    client: {
      observe: async (nextScope) => ({
        ...channelsObservation(nextScope),
        allowedActions: [
          'view',
          'view-channel-catalog',
          'view-channel-schema',
          'list-channel-configs',
          'create-channel-config',
          'update-channel-config',
          'delete-channel-config',
          'test-channel-config',
        ],
        itemCount: 1,
        catalog: [channelCatalog()],
        configs: [channelConfig()],
      }),
      getSchema: async () => channelSchema(),
      create: async () => channelConfig(),
      update: async () => channelConfig(),
      test: async () => ({ success: true, message: 'ok' }),
      remove: async () => {},
    },
    initialScope: scope,
  });
}

function completeTemplatesController(scope) {
  return createTemplatesRouteController({
    client: {
      observe: async (nextScope) => ({
        ...templatesObservation(nextScope),
        allowedActions: [
          'view',
          'list',
          'search',
          'filter',
          'view-detail',
          'install',
          'seed',
          'retry',
        ],
      }),
      get: async () => templateDetail(),
      install: async () => {},
      seed: async () => 0,
    },
    initialScope: scope,
  });
}

function completeProfileController(scope, observation) {
  return createProfileRouteController({
    client: {
      observe: async () => observation,
      update: async (_scope, input) => currentUser(input),
      changePassword: async () => {},
    },
    initialScope: scope,
  });
}

function renderRoute(element) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null, element));
}

function assertActions(markup, actions) {
  for (const action of actions) {
    assert.match(markup, new RegExp(`data-action="${action}"`, 'u'));
  }
}
