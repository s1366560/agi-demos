import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SettingsWindow, type SettingsSection } from '../features/settings/SettingsWindow';
import { I18nProvider } from '../i18n';
import type {
  AuthState,
  DesktopRuntimeConfig,
  LlmProviderAuthMethod,
  LlmProviderRoutingPolicy,
  LlmRouteTarget,
  ManagedAgentDefinition,
  ManagedLlmProvider,
  ManagedPlugin,
  ManagedSkill,
} from '../types';
import { DEFAULT_CONFIG } from '../types';
import '../styles.css';

type QaPlugin = Omit<ManagedPlugin, 'id'> & { id?: string };

declare global {
  var __providerSettingsQaRoot: Root | undefined;
}

const QA_API_ORIGIN = 'https://qa.memstack.invalid';
const QA_TENANT_ID = 'tenant-northstar';
const QA_PROJECT_ID = 'project-desktop-client';
const QA_WORKSPACE_ID = 'workspace-desktop-client';
const NOW = '2026-07-14T09:40:00.000Z';
const QA_ENVIRONMENT_SECRETS = new Set(['ANTHROPIC_API_KEY', 'OPENAI_API_KEY']);

const qaProviderTypes = [
  {
    provider_type: 'openai',
    operation_type: 'llm',
    auth_methods: ['api_key', 'environment'],
    unavailable_auth_methods: ['oauth'],
    probe_supported: true,
  },
  {
    provider_type: 'anthropic',
    operation_type: 'llm',
    auth_methods: ['api_key', 'environment'],
    unavailable_auth_methods: ['oauth'],
    probe_supported: true,
  },
  {
    provider_type: 'openai_compatible',
    operation_type: 'llm',
    auth_methods: ['api_key', 'environment', 'none'],
    unavailable_auth_methods: ['oauth'],
    probe_supported: true,
  },
] as const;

const initialProviders: ManagedLlmProvider[] = [
  {
    id: 'provider-openai',
    name: 'OpenAI',
    provider_type: 'openai',
    operation_type: 'llm',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://api.openai.com/v1',
    llm_model: 'gpt-5.1',
    llm_small_model: 'gpt-5.1-mini',
    embedding_model: 'text-embedding-3-large',
    allowed_models: ['gpt-5.1', 'gpt-5.1-mini', 'gpt-4.1'],
    secondary_models: ['gpt-5.1-mini'],
    health_status: 'healthy',
    credential_source: 'system_vault',
    credential_configured: true,
    api_key_masked: '••••••••••7K2J',
    health_last_check: NOW,
    response_time_ms: 184,
    revision: 14,
    updated_at: NOW,
  },
  {
    id: 'provider-anthropic',
    name: 'Anthropic',
    provider_type: 'anthropic',
    operation_type: 'llm',
    auth_method: 'environment',
    is_active: true,
    is_enabled: true,
    base_url: 'https://api.anthropic.com/v1',
    llm_model: 'claude-sonnet-4-5',
    llm_small_model: 'claude-haiku-4-5',
    allowed_models: ['claude-sonnet-4-5', 'claude-haiku-4-5'],
    secondary_models: ['claude-haiku-4-5'],
    health_status: 'healthy',
    credential_source: 'environment',
    credential_configured: true,
    environment_variable: 'ANTHROPIC_API_KEY',
    health_last_check: NOW,
    response_time_ms: 211,
    revision: 9,
    updated_at: NOW,
  },
  {
    id: 'provider-local-gateway',
    name: 'Local Gateway',
    provider_type: 'openai_compatible',
    operation_type: 'llm',
    auth_method: 'none',
    is_active: true,
    is_enabled: true,
    base_url: 'http://127.0.0.1:11434/v1',
    llm_model: 'qwen3-coder',
    llm_small_model: 'qwen3',
    allowed_models: ['qwen3-coder', 'qwen3'],
    secondary_models: ['qwen3'],
    health_status: 'healthy',
    credential_source: 'none',
    credential_configured: true,
    health_last_check: NOW,
    response_time_ms: 38,
    revision: 6,
    updated_at: NOW,
  },
];

const initialRoutingPolicy: LlmProviderRoutingPolicy = {
  tenant_id: QA_TENANT_ID,
  project_id: QA_PROJECT_ID,
  workspace_id: QA_WORKSPACE_ID,
  revision: 4,
  roles: {
    default: { provider_id: 'provider-openai', model_id: 'gpt-5.1' },
    fast: { provider_id: 'provider-openai', model_id: 'gpt-5.1-mini' },
    coding: { provider_id: 'provider-anthropic', model_id: 'claude-sonnet-4-5' },
    vision: { provider_id: 'provider-openai', model_id: 'gpt-4.1' },
  },
  fallbacks: [
    { provider_id: 'provider-anthropic', model_id: 'claude-sonnet-4-5' },
    { provider_id: 'provider-local-gateway', model_id: 'qwen3-coder' },
  ],
  updated_at: NOW,
};

const modelCatalogs: Record<string, Record<'chat' | 'embedding' | 'rerank', string[]>> = {
  openai: {
    chat: ['gpt-5.1', 'gpt-5.1-mini', 'gpt-4.1'],
    embedding: ['text-embedding-3-large', 'text-embedding-3-small'],
    rerank: [],
  },
  anthropic: {
    chat: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-1'],
    embedding: [],
    rerank: [],
  },
  openai_compatible: {
    chat: ['qwen3-coder', 'qwen3'],
    embedding: [],
    rerank: [],
  },
};

let providers = initialProviders.map((provider) => ({ ...provider }));
let routingPolicy = initialRoutingPolicy;

let skills: ManagedSkill[] = [
  {
    id: 'competitive-research',
    name: 'Competitive research',
    description: 'Builds an evidence-backed market brief from verified sources.',
    status: 'active',
    scope: 'tenant',
    tools: ['web_search', 'browser', 'documents', 'citations'],
    current_version: 4,
    is_system_skill: false,
    updated_at: NOW,
  },
  {
    id: 'code-verification',
    name: 'Code verification',
    description: 'Runs tests and collects structured review evidence.',
    status: 'active',
    scope: 'system',
    tools: ['run_tests', 'analyze_coverage', 'git_diff'],
    current_version: 2,
    is_system_skill: true,
    updated_at: '2026-07-13T08:20:00.000Z',
  },
  {
    id: 'meeting-brief',
    name: 'Meeting brief',
    description: 'Prepares an agenda and decision record from project context.',
    status: 'disabled',
    scope: 'tenant',
    tools: ['read', 'documents'],
    current_version: 1,
    is_system_skill: false,
    updated_at: '2026-07-11T05:20:00.000Z',
  },
];

let plugins: QaPlugin[] = [
  {
    name: 'github',
    source: 'entrypoint',
    package: '@memstack/github',
    version: '2.4.1',
    kind: 'mcp',
    enabled: true,
    discovered: true,
    providers: ['github'],
    skills: ['pull-request-review'],
    channel_types: ['issues', 'pull_requests'],
    tool_definitions: [
      { name: 'list_pull_requests' },
      { name: 'review_pull_request' },
      { name: 'read_issue' },
    ],
    updated_at: NOW,
  },
  {
    name: 'slack',
    source: 'entrypoint',
    package: '@memstack/slack',
    version: '3.2.0',
    kind: 'channel',
    enabled: true,
    discovered: true,
    providers: ['slack'],
    skills: ['incident-triage'],
    channel_types: ['messages', 'threads'],
    tool_definitions: [{ name: 'search_messages' }, { name: 'post_message' }],
    updated_at: NOW,
  },
  {
    name: 'google-drive',
    source: 'entrypoint',
    package: '@memstack/google-drive',
    version: '1.8.0',
    kind: 'channel',
    enabled: false,
    discovered: false,
    providers: ['google'],
    skills: [],
    channel_types: ['documents'],
    tool_definitions: [],
    updated_at: '2026-07-09T04:10:00.000Z',
  },
];

let agents: ManagedAgentDefinition[] = [
  {
    id: 'agent-atlas',
    name: 'atlas',
    display_name: 'Atlas',
    system_prompt: 'Internal prompt must never be rendered or searched.',
    enabled: true,
    status: 'active',
    model: 'openai/gpt-5.1',
    project_id: QA_PROJECT_ID,
    allowed_tools: ['web_search', 'browser', 'documents'],
    allowed_skills: ['competitive-research', 'meeting-brief'],
    allowed_mcp_servers: ['github'],
    fallback_models: ['anthropic/claude-sonnet-4-5'],
    updated_at: NOW,
  },
  {
    id: 'agent-reviewer',
    name: 'review_guardian',
    display_name: 'Review guardian',
    system_prompt: 'Private review policy.',
    enabled: false,
    status: 'disabled',
    model_name: 'anthropic/claude-sonnet-4-5',
    project_id: QA_PROJECT_ID,
    allowed_tools: ['read', 'git_diff'],
    allowed_skills: ['code-verification'],
    allowed_mcp_servers: ['github'],
    updated_at: '2026-07-12T09:10:00.000Z',
  },
  {
    id: 'builtin:all-access',
    name: 'local_agent',
    display_name: 'General and coding Agent',
    enabled: true,
    status: 'active',
    model_name: null,
    project_id: QA_PROJECT_ID,
    allowed_tools: ['read', 'write', 'edit', 'terminal'],
    allowed_skills: ['code-verification'],
    allowed_mcp_servers: ['local-runtime'],
    updated_at: NOW,
  },
];

const qaAuth: AuthState = {
  status: 'signed_in',
  credentialKind: 'cloud_session',
  session: {
    session_id: 'qa-provider-settings-session',
    auth_method: 'workspace_sso',
    expires_at: '2026-07-15T09:40:00.000Z',
    trusted_device: true,
  },
  context: {
    tenant_id: QA_TENANT_ID,
    project_id: QA_PROJECT_ID,
    revision: 8,
    updated_at: NOW,
  },
  user: {
    user_id: 'user-alex-chen',
    email: 'alex.chen@northstar.example',
    name: 'Alex Chen',
    roles: ['admin'],
    is_active: true,
    created_at: '2025-11-18T02:00:00.000Z',
    profile: { title: 'Platform administrator' },
    preferred_language: 'zh-CN',
  },
  tenants: [
    {
      id: QA_TENANT_ID,
      name: 'Northstar Labs',
      slug: 'northstar-labs',
      plan: 'enterprise',
    },
  ],
  projects: [
    {
      id: QA_PROJECT_ID,
      tenant_id: QA_TENANT_ID,
      name: 'Desktop Client',
      description: 'Desktop application and agent runtime',
    },
  ],
  mustChangePassword: false,
  error: null,
};

const qaConfig: DesktopRuntimeConfig = {
  ...DEFAULT_CONFIG,
  apiBaseUrl: QA_API_ORIGIN,
  apiKey: 'qa-session-placeholder',
  tenantId: QA_TENANT_ID,
  projectId: QA_PROJECT_ID,
  workspaceId: QA_WORKSPACE_ID,
  mode: 'local',
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestDetails(input: RequestInfo | URL, init?: RequestInit) {
  const request = input instanceof Request ? input : null;
  const url = new URL(request?.url ?? String(input), window.location.href);
  const method = (init?.method ?? request?.method ?? 'GET').toUpperCase();
  const body = init?.body ?? null;
  return { url, method, body };
}

function readJsonBody(body: BodyInit | null): Record<string, unknown> {
  if (typeof body !== 'string' || !body) return {};
  try {
    const parsed = JSON.parse(body) as unknown;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function stringArray(value: unknown, fallback: string[] = []): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function isRouteTarget(value: unknown): value is LlmRouteTarget {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const target = value as Record<string, unknown>;
  const keys = Object.keys(target).sort();
  return (
    keys.length === 2 &&
    keys[0] === 'model_id' &&
    keys[1] === 'provider_id' &&
    typeof target.provider_id === 'string' &&
    target.provider_id.trim().length > 0 &&
    typeof target.model_id === 'string' &&
    target.model_id.trim().length > 0
  );
}

function isRoutingRoles(value: unknown): value is LlmProviderRoutingPolicy['roles'] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const roles = value as Record<string, unknown>;
  const roleNames = ['coding', 'default', 'fast', 'vision'];
  return (
    JSON.stringify(Object.keys(roles).sort()) === JSON.stringify(roleNames) &&
    roleNames.every((role) => roles[role] === null || isRouteTarget(roles[role]))
  );
}

function routingTargetAvailable(target: LlmRouteTarget): boolean {
  const provider = providers.find((item) => item.id === target.provider_id);
  if (!provider) return false;
  const supportedProvider = ['anthropic', 'openai', 'openai_compatible'].includes(
    provider.provider_type,
  );
  const credentialReady =
    provider.auth_method === 'none' || provider.credential_configured === true;
  const models = new Set([provider.llm_model, ...(provider.allowed_models ?? [])].filter(Boolean));
  return Boolean(
    supportedProvider &&
      ['configuration_valid', 'healthy'].includes(provider.health_status ?? '') &&
      provider.is_active === true &&
      provider.is_enabled !== false &&
      provider.base_url?.trim() &&
      credentialReady &&
      models.has(target.model_id),
  );
}

function safeProviderFromBody(
  body: Record<string, unknown>,
  current?: ManagedLlmProvider,
): ManagedLlmProvider {
  const nextRevision = (current?.revision ?? 0) + 1;
  const apiKeySubmitted = Boolean(stringValue(body.api_key).trim());
  const rawAuthMethod = stringValue(body.auth_method, current?.auth_method ?? 'api_key');
  const authMethod: LlmProviderAuthMethod = [
    'api_key',
    'environment',
    'none',
  ].includes(rawAuthMethod)
    ? (rawAuthMethod as LlmProviderAuthMethod)
    : 'api_key';
  const environmentVariable =
    authMethod === 'environment'
      ? stringValue(body.environment_variable, current?.environment_variable ?? '').trim()
      : '';
  const storedCredentialReusable =
    current?.auth_method === authMethod &&
    current.credential_configured === true &&
    (authMethod !== 'environment' || current.environment_variable === environmentVariable);
  const active = booleanValue(body.is_active, current?.is_active ?? false);
  const baseUrl = stringValue(body.base_url, current?.base_url ?? '');
  const primaryModel = stringValue(body.llm_model, current?.llm_model ?? '');
  const credentialConfigured =
    authMethod === 'none' ||
    storedCredentialReusable ||
    (authMethod === 'api_key' && apiKeySubmitted) ||
    (authMethod === 'environment' && QA_ENVIRONMENT_SECRETS.has(environmentVariable));
  const healthStatus =
    !active || !baseUrl || !primaryModel
      ? 'not_configured'
      : credentialConfigured
        ? 'not_checked'
        : 'needs_credentials';
  return {
    ...(current ?? {}),
    id: current?.id ?? `provider-${crypto.randomUUID()}`,
    name: stringValue(body.name, current?.name ?? 'New provider'),
    provider_type: stringValue(body.provider_type, current?.provider_type ?? 'openai'),
    operation_type: current?.operation_type ?? 'llm',
    auth_method: authMethod,
    is_active: active,
    is_enabled: active,
    base_url: baseUrl,
    llm_model: primaryModel,
    allowed_models: stringArray(body.allowed_models, current?.allowed_models ?? []),
    health_status: healthStatus,
    credential_configured: credentialConfigured,
    credential_source:
      authMethod === 'none'
        ? 'none'
        : authMethod === 'environment'
          ? 'environment'
          : 'system_vault',
    environment_variable: authMethod === 'environment' ? environmentVariable : null,
    api_key_masked:
      authMethod === 'api_key'
        ? current?.auth_method === 'api_key' && current.api_key_masked
          ? current.api_key_masked
          : apiKeySubmitted
            ? '••••••••••NEW'
            : null
        : null,
    health_last_check: null,
    response_time_ms: null,
    error_message: null,
    revision: nextRevision,
    updated_at: NOW,
  };
}

async function providerQaFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const { url, method, body } = requestDetails(input, init);
  if (url.origin !== QA_API_ORIGIN) {
    return jsonResponse({ detail: 'QA harness blocks requests outside its controlled API.' }, 403);
  }

  const path = url.pathname;
  if (method === 'GET' && path === '/api/v1/projects') {
    return jsonResponse({ projects: qaAuth.projects });
  }
  if (method === 'GET' && path === '/api/v1/skills/') {
    return jsonResponse({ skills });
  }
  if (method === 'GET' && path.endsWith('/plugins')) {
    return jsonResponse({ plugins });
  }
  if (method === 'GET' && path === '/api/v1/agent/definitions') {
    return jsonResponse({ definitions: agents });
  }
  if (method === 'GET' && path === '/api/v1/llm-providers/') {
    return jsonResponse(providers);
  }
  if (path === '/api/v1/llm-providers/routing-policy') {
    if (method === 'GET') {
      if (
        url.searchParams.get('project_id') !== QA_PROJECT_ID ||
        url.searchParams.get('workspace_id') !== QA_WORKSPACE_ID
      ) {
        return jsonResponse({ detail: 'Workspace routing scope is required.' }, 422);
      }
      return jsonResponse(routingPolicy);
    }
    if (method === 'PUT') {
      const draft = readJsonBody(body);
      if (draft.expected_revision !== routingPolicy.revision) {
        return jsonResponse({ detail: 'Routing policy revision conflict.' }, 409);
      }
      if (
        !isRoutingRoles(draft.roles) ||
        !Array.isArray(draft.fallbacks) ||
        !draft.fallbacks.every(isRouteTarget) ||
        draft.roles.default === null ||
        draft.project_id !== QA_PROJECT_ID ||
        draft.workspace_id !== QA_WORKSPACE_ID ||
        draft.fallbacks.length > 8
      ) {
        return jsonResponse({ detail: 'Invalid routing policy.' }, 422);
      }
      const targets = [
        ...Object.values(draft.roles).filter((target): target is LlmRouteTarget => target !== null),
        ...draft.fallbacks,
      ];
      const fallbackKeys = draft.fallbacks.map((target) =>
        JSON.stringify([target.provider_id, target.model_id]),
      );
      if (
        targets.some((target) => !routingTargetAvailable(target)) ||
        new Set(fallbackKeys).size !== fallbackKeys.length
      ) {
        return jsonResponse({ detail: 'Routing target is unavailable.' }, 422);
      }
      routingPolicy = {
        ...routingPolicy,
        revision: routingPolicy.revision + 1,
        roles: { ...draft.roles },
        fallbacks: [...draft.fallbacks],
        updated_at: new Date().toISOString(),
      };
      return jsonResponse(routingPolicy);
    }
  }
  if (method === 'GET' && path === '/api/v1/llm-providers/types') {
    return jsonResponse({ types: qaProviderTypes });
  }

  const catalogMatch = path.match(/^\/api\/v1\/llm-providers\/models\/([^/]+)$/);
  if (method === 'GET' && catalogMatch) {
    const providerType = decodeURIComponent(catalogMatch[1]);
    const catalog = modelCatalogs[providerType];
    return catalog
      ? jsonResponse({ source: 'qa_provider_registry', models: catalog })
      : jsonResponse({ detail: 'Provider model catalog not found.' }, 404);
  }

  const discoveryMatch = path.match(
    /^\/api\/v1\/llm-providers\/([^/]+)\/models\/discover$/,
  );
  if (method === 'POST' && discoveryMatch) {
    const providerId = decodeURIComponent(discoveryMatch[1]);
    const provider = providers.find((item) => item.id === providerId);
    if (!provider) return jsonResponse({ detail: 'Provider not found.' }, 404);
    const draft = readJsonBody(body);
    if (draft.expected_revision !== provider.revision) {
      return jsonResponse({ detail: 'Provider revision conflict.' }, 409);
    }
    const catalog = modelCatalogs[provider.provider_type];
    return jsonResponse({
      provider_type: provider.provider_type,
      provider_id: provider.id,
      availability: catalog ? 'available' : 'unavailable',
      source: catalog ? 'provider-api' : null,
      discovered_at: NOW,
      detail: catalog ? null : 'This endpoint does not expose model discovery.',
      models: catalog ?? { chat: [], embedding: [], rerank: [] },
    });
  }

  if (method === 'POST' && path === '/api/v1/llm-providers/test-connection') {
    const draft = readJsonBody(body);
    const providerType = stringValue(draft.provider_type);
    const authMethod = stringValue(draft.auth_method, 'api_key');
    const environmentVariable = stringValue(draft.environment_variable).trim();
    const catalog = modelCatalogs[providerType];
    const configured = Boolean(
      stringValue(draft.name) &&
        providerType &&
        stringValue(draft.base_url) &&
        (authMethod === 'none' ||
          (authMethod === 'api_key' && stringValue(draft.api_key)) ||
          (authMethod === 'environment' &&
            QA_ENVIRONMENT_SECRETS.has(environmentVariable))),
    );
    return jsonResponse({
      status: configured ? 'healthy' : 'needs_credentials',
      probed: true,
      detail: configured
        ? 'Authentication and endpoint connectivity verified.'
        : 'The provider credential is required.',
      last_check: NOW,
      response_time_ms: configured ? 176 : null,
      error_message: configured ? null : 'Required connection fields are missing.',
      catalog: configured
        ? {
            provider_type: providerType,
            provider_id: null,
            availability: catalog ? 'available' : 'unavailable',
            source: catalog ? 'provider-api' : null,
            discovered_at: NOW,
            detail: catalog ? null : 'This endpoint does not expose model discovery.',
            models: catalog ?? { chat: [], embedding: [], rerank: [] },
          }
        : null,
    });
  }

  const skillStatusMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/status$/);
  if (method === 'PATCH' && skillStatusMatch) {
    const skillId = decodeURIComponent(skillStatusMatch[1]);
    const status = url.searchParams.get('status') ?? 'disabled';
    skills = skills.map((skill) => (skill.id === skillId ? { ...skill, status } : skill));
    return jsonResponse(skills.find((skill) => skill.id === skillId) ?? null);
  }

  const pluginStatusMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/([^/]+)\/(enable|disable)$/,
  );
  if (method === 'POST' && pluginStatusMatch) {
    const pluginName = decodeURIComponent(pluginStatusMatch[1]);
    const enabled = pluginStatusMatch[2] === 'enable';
    plugins = plugins.map((plugin) =>
      plugin.name === pluginName ? { ...plugin, enabled } : plugin,
    );
    return jsonResponse(plugins.find((plugin) => plugin.name === pluginName) ?? null);
  }

  const agentStatusMatch = path.match(/^\/api\/v1\/agent\/definitions\/([^/]+)\/enabled$/);
  if (method === 'PATCH' && agentStatusMatch) {
    const agentId = decodeURIComponent(agentStatusMatch[1]);
    const enabled = booleanValue(readJsonBody(body).enabled, false);
    agents = agents.map((agent) =>
      agent.id === agentId
        ? { ...agent, enabled, status: enabled ? 'active' : 'disabled' }
        : agent,
    );
    return jsonResponse(agents.find((agent) => agent.id === agentId) ?? null);
  }

  if (method === 'POST' && path === '/api/v1/llm-providers/') {
    const created = safeProviderFromBody(readJsonBody(body));
    providers = [...providers, created];
    return jsonResponse(created, 201);
  }

  const usageMatch = path.match(/^\/api\/v1\/llm-providers\/([^/]+)\/usage$/);
  if (method === 'GET' && usageMatch) {
    const providerId = decodeURIComponent(usageMatch[1]);
    return jsonResponse({
      provider_id: providerId,
      tenant_id: QA_TENANT_ID,
      statistics: [
        {
          provider_id: providerId,
          tenant_id: QA_TENANT_ID,
          operation_type: 'llm',
          total_requests: 18420,
          total_prompt_tokens: 12864200,
          total_completion_tokens: 3148900,
          total_tokens: 16013100,
          total_cost_usd: 382.47,
          avg_response_time_ms: 294,
          first_request_at: '2026-07-01T00:00:00.000Z',
          last_request_at: NOW,
        },
      ],
    });
  }

  const healthMatch = path.match(/^\/api\/v1\/llm-providers\/([^/]+)\/health-check$/);
  if (method === 'POST' && healthMatch) {
    const providerId = decodeURIComponent(healthMatch[1]);
    const provider = providers.find((item) => item.id === providerId);
    if (!provider) return jsonResponse({ detail: 'Provider not found.' }, 404);
    const draft = readJsonBody(body);
    if (draft.expected_revision !== provider.revision) {
      return jsonResponse({ detail: 'Provider revision conflict.' }, 409);
    }
    providers = providers.map((item) =>
      item.id === providerId
        ? {
            ...item,
            health_status: 'healthy',
            health_last_check: NOW,
            response_time_ms: 172,
            error_message: null,
          }
        : item,
    );
    return jsonResponse({
      status: 'healthy',
      probed: true,
      detail: 'Authentication and endpoint connectivity verified.',
      last_check: NOW,
      response_time_ms: 172,
      error_message: null,
      catalog: {
        provider_type: provider.provider_type,
        provider_id: provider.id,
        availability: 'available',
        source: 'provider-api',
        discovered_at: NOW,
        detail: null,
        models: modelCatalogs[provider.provider_type],
      },
    });
  }

  const providerMatch = path.match(/^\/api\/v1\/llm-providers\/([^/]+)$/);
  if (method === 'PUT' && providerMatch) {
    const providerId = decodeURIComponent(providerMatch[1]);
    const current = providers.find((item) => item.id === providerId);
    if (!current) return jsonResponse({ detail: 'Provider not found.' }, 404);
    const updated = safeProviderFromBody(readJsonBody(body), current);
    providers = providers.map((item) => (item.id === providerId ? updated : item));
    return jsonResponse(updated);
  }

  return jsonResponse({ detail: `Unhandled QA route: ${method} ${path}` }, 404);
}

globalThis.fetch = providerQaFetch;
try {
  window.localStorage.setItem('agistack.desktop.locale', 'zh-CN');
} catch {
  // The QA page still falls back to the browser language when storage is unavailable.
}

function ProviderSettingsQa() {
  const [config, setConfig] = useState<DesktopRuntimeConfig>(qaConfig);
  const requestedSection = new URLSearchParams(window.location.search).get('section');
  const supportedSections = new Set<SettingsSection>([
    'account',
    'workspace',
    'general',
    'appearance',
    'notifications',
    'models',
    'skills',
    'plugins',
    'agents',
    'connection',
  ]);
  const initialSection =
    requestedSection && supportedSections.has(requestedSection as SettingsSection)
      ? (requestedSection as SettingsSection)
      : 'models';
  return (
    <SettingsWindow
      open
      initialSection={initialSection}
      auth={qaAuth}
      config={config}
      runtimeProvider={null}
      connection="ready"
      wsConnected
      wsError={null}
      runtimeDisabledReason={null}
      onClose={() => undefined}
      onConfigChange={setConfig}
      onRuntimeStatusRefresh={async () => undefined}
      onRefreshRuntime={() => undefined}
      onContextChange={async () => undefined}
      onSignOut={() => undefined}
    />
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__providerSettingsQaRoot ?? createRoot(root);
globalThis.__providerSettingsQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <ProviderSettingsQa />
    </I18nProvider>
  </React.StrictMode>,
);
