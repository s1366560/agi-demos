import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SettingsWindow } from '../features/settings/SettingsWindow';
import { I18nProvider } from '../i18n';
import type {
  AuthState,
  DesktopRuntimeConfig,
  ManagedLlmProvider,
} from '../types';
import { DEFAULT_CONFIG } from '../types';
import '../styles.css';

declare global {
  var __providerSettingsQaRoot: Root | undefined;
}

const QA_API_ORIGIN = 'https://qa.memstack.invalid';
const QA_TENANT_ID = 'tenant-northstar';
const QA_PROJECT_ID = 'project-desktop-client';
const NOW = '2026-07-14T09:40:00.000Z';

const initialProviders: ManagedLlmProvider[] = [
  {
    id: 'provider-openai',
    name: 'OpenAI',
    provider_type: 'openai',
    operation_type: 'chat',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://api.openai.com/v1',
    llm_model: 'gpt-5.1',
    llm_small_model: 'gpt-5.1-mini',
    embedding_model: 'text-embedding-3-large',
    allowed_models: ['gpt-5.1', 'gpt-5.1-mini', 'text-embedding-3-large'],
    secondary_models: ['gpt-5.1-mini'],
    health_status: 'healthy',
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
    operation_type: 'chat',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://api.anthropic.com',
    llm_model: 'claude-sonnet-4-5',
    llm_small_model: 'claude-haiku-4-5',
    allowed_models: ['claude-sonnet-4-5', 'claude-haiku-4-5'],
    secondary_models: ['claude-haiku-4-5'],
    health_status: 'healthy',
    credential_configured: true,
    api_key_masked: '••••••••••B91Q',
    health_last_check: '2026-07-14T09:38:00.000Z',
    response_time_ms: 226,
    revision: 9,
    updated_at: NOW,
  },
  {
    id: 'provider-google-ai',
    name: 'Google AI',
    provider_type: 'gemini',
    operation_type: 'chat',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://generativelanguage.googleapis.com/v1beta',
    llm_model: 'gemini-2.5-pro',
    llm_small_model: 'gemini-2.5-flash',
    allowed_models: ['gemini-2.5-pro', 'gemini-2.5-flash'],
    secondary_models: ['gemini-2.5-flash'],
    health_status: 'healthy',
    credential_configured: true,
    api_key_masked: '••••••••••M4X8',
    health_last_check: '2026-07-14T09:36:00.000Z',
    response_time_ms: 201,
    revision: 6,
    updated_at: NOW,
  },
  {
    id: 'provider-openrouter',
    name: 'OpenRouter',
    provider_type: 'openrouter',
    operation_type: 'chat',
    auth_method: 'api_key',
    is_active: true,
    is_enabled: true,
    base_url: 'https://openrouter.ai/api/v1',
    llm_model: 'anthropic/claude-sonnet-4.5',
    allowed_models: ['anthropic/claude-sonnet-4.5', 'openai/gpt-5.1'],
    health_status: 'rate_limited',
    credential_configured: true,
    api_key_masked: '••••••••••R2P6',
    health_last_check: '2026-07-14T09:31:00.000Z',
    response_time_ms: 612,
    error_message: 'Provider quota requires attention.',
    revision: 3,
    updated_at: NOW,
  },
  {
    id: 'provider-ollama',
    name: 'Ollama',
    provider_type: 'ollama',
    operation_type: 'chat',
    auth_method: 'none',
    is_active: false,
    is_enabled: false,
    base_url: 'http://127.0.0.1:11434/v1',
    llm_model: 'qwen3-coder',
    allowed_models: ['qwen3-coder', 'llama3.3'],
    health_status: 'offline',
    credential_configured: false,
    health_last_check: '2026-07-14T08:54:00.000Z',
    error_message: 'Local endpoint is unavailable from the cloud runtime.',
    revision: 2,
    updated_at: NOW,
  },
];

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
  gemini: {
    chat: ['gemini-2.5-pro', 'gemini-2.5-flash'],
    embedding: ['text-embedding-004'],
    rerank: [],
  },
  openrouter: {
    chat: ['anthropic/claude-sonnet-4.5', 'openai/gpt-5.1', 'google/gemini-2.5-pro'],
    embedding: [],
    rerank: [],
  },
  ollama: {
    chat: ['qwen3-coder', 'llama3.3'],
    embedding: ['nomic-embed-text'],
    rerank: [],
  },
};

let providers = initialProviders.map((provider) => ({ ...provider }));

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
  workspaceId: 'workspace-desktop-client',
  mode: 'cloud',
  llmProvider: 'openai',
  llmBaseUrl: 'https://api.openai.com/v1',
  llmModel: 'gpt-5.1',
  llmApiKey: '',
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

function safeProviderFromBody(
  body: Record<string, unknown>,
  current?: ManagedLlmProvider,
): ManagedLlmProvider {
  const nextRevision = (current?.revision ?? 0) + 1;
  const apiKeySubmitted = Boolean(stringValue(body.api_key).trim());
  return {
    ...(current ?? {}),
    id: current?.id ?? `provider-${crypto.randomUUID()}`,
    name: stringValue(body.name, current?.name ?? 'New provider'),
    provider_type: stringValue(body.provider_type, current?.provider_type ?? 'openai'),
    operation_type: current?.operation_type ?? 'chat',
    auth_method: current?.auth_method ?? 'api_key',
    is_active: booleanValue(body.is_active, current?.is_active ?? false),
    is_enabled: booleanValue(body.is_active, current?.is_enabled ?? false),
    base_url: stringValue(body.base_url, current?.base_url ?? ''),
    llm_model: stringValue(body.llm_model, current?.llm_model ?? ''),
    allowed_models: stringArray(body.allowed_models, current?.allowed_models ?? []),
    health_status: current?.health_status ?? 'healthy',
    credential_configured: current?.credential_configured || apiKeySubmitted,
    api_key_masked:
      current?.api_key_masked || (apiKeySubmitted ? '••••••••••NEW' : null),
    health_last_check: NOW,
    response_time_ms: current?.response_time_ms ?? 210,
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
  if (method === 'GET' && path === '/api/v1/llm-providers/') {
    return jsonResponse(providers);
  }
  if (method === 'GET' && path === '/api/v1/llm-providers/types') {
    return jsonResponse({ types: ['openai', 'anthropic', 'gemini', 'openrouter', 'ollama'] });
  }

  const catalogMatch = path.match(/^\/api\/v1\/llm-providers\/models\/([^/]+)$/);
  if (method === 'GET' && catalogMatch) {
    const providerType = decodeURIComponent(catalogMatch[1]);
    const catalog = modelCatalogs[providerType];
    return catalog
      ? jsonResponse({ source: 'qa_provider_registry', models: catalog })
      : jsonResponse({ detail: 'Provider model catalog not found.' }, 404);
  }

  if (method === 'POST' && path === '/api/v1/llm-providers/test-connection') {
    const draft = readJsonBody(body);
    const configured = Boolean(
      stringValue(draft.name) &&
        stringValue(draft.provider_type) &&
        stringValue(draft.base_url) &&
        stringValue(draft.llm_model),
    );
    return jsonResponse({
      status: configured ? 'healthy' : 'configuration_invalid',
      last_check: NOW,
      response_time_ms: configured ? 196 : null,
      error_message: configured ? null : 'Required connection fields are missing.',
    });
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
          operation_type: 'chat',
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
    providers = providers.map((item) =>
      item.id === providerId
        ? {
            ...item,
            health_status: 'healthy',
            health_last_check: NOW,
            response_time_ms: 188,
            error_message: null,
          }
        : item,
    );
    return jsonResponse({
      status: 'healthy',
      last_check: NOW,
      response_time_ms: 188,
      error_message: null,
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
  return (
    <SettingsWindow
      open
      initialSection="models"
      auth={qaAuth}
      config={config}
      connection="ready"
      wsConnected
      wsError={null}
      runtimeDisabledReason={null}
      onClose={() => undefined}
      onConfigChange={setConfig}
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
