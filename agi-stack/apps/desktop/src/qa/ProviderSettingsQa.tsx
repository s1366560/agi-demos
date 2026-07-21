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
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedLlmProvider,
  ManagedPlugin,
  ManagedSkill,
  ManagedSkillEvolutionDetail,
  ManagedSkillEvolutionJob,
  ManagedSkillVersion,
  ManagedSubAgent,
  ManagedSubAgentTemplate,
  PluginConfigRecord,
  PluginConfigSchema,
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
    credential_source: 'application_vault',
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
    coding: {
      provider_id: 'provider-anthropic',
      model_id: 'claude-sonnet-4-5',
    },
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
    tenant_id: QA_TENANT_ID,
    project_id: null,
    name: 'competitive-research',
    description: 'Builds an evidence-backed market brief from verified sources.',
    status: 'active',
    scope: 'tenant',
    tools: ['web_search', 'browser', 'documents', 'citations'],
    current_version: 4,
    is_system_skill: false,
    full_content:
      '---\nname: competitive-research\ndescription: "Builds an evidence-backed market brief from verified sources."\n---\n\n# Competitive research\n\nVerify every source.\n',
    metadata: { owner: 'strategy' },
    spec_version: '1.0',
    updated_at: NOW,
  },
  {
    id: 'code-verification',
    name: 'code-verification',
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
    tenant_id: QA_TENANT_ID,
    project_id: null,
    name: 'meeting-brief',
    description: 'Prepares an agenda and decision record from project context.',
    status: 'disabled',
    scope: 'tenant',
    tools: ['read', 'documents'],
    current_version: 1,
    is_system_skill: false,
    full_content:
      '---\nname: meeting-brief\ndescription: "Prepares an agenda and decision record from project context."\n---\n\n# Meeting brief\n',
    metadata: {},
    spec_version: '1.0',
    updated_at: '2026-07-11T05:20:00.000Z',
  },
];

let skillVersions: Record<string, ManagedSkillVersion[]> = {
  'competitive-research': [
    {
      id: 'competitive-research-v4',
      skill_id: 'competitive-research',
      version_number: 4,
      version_label: '1.3.0',
      change_summary: 'Require a source-quality review before synthesis.',
      created_by: 'agent',
      created_at: NOW,
    },
    {
      id: 'competitive-research-v3',
      skill_id: 'competitive-research',
      version_number: 3,
      version_label: '1.2.0',
      change_summary: 'Add citation verification.',
      created_by: 'import',
      created_at: '2026-07-12T06:10:00.000Z',
    },
  ],
  'meeting-brief': [
    {
      id: 'meeting-brief-v1',
      skill_id: 'meeting-brief',
      version_number: 1,
      version_label: '1.0.0',
      change_summary: 'Initial package import.',
      created_by: 'import',
      created_at: '2026-07-11T05:20:00.000Z',
    },
  ],
};

let skillEvolutionJobs: ManagedSkillEvolutionJob[] = [
  {
    id: 'competitive-research-evolution-1',
    project_id: null,
    skill_name: 'competitive-research',
    action: 'update',
    status: 'pending_review',
    rationale: 'Recent sessions request clearer source confidence checks.',
    candidate_preview: 'Add a confidence note for every cited source.',
    candidate_content: '# Competitive research\n\nAdd a confidence note for every cited source.',
    blocked_by_review: true,
    session_ids: ['session-1', 'session-2'],
    skill_version_id: null,
    created_at: NOW,
    applied_at: null,
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
    schema_supported: true,
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
    schema_supported: true,
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
    schema_supported: false,
    updated_at: '2026-07-09T04:10:00.000Z',
  },
];

const pluginSchemas: Record<string, PluginConfigSchema> = {
  github: {
    plugin_name: 'github',
    source: 'entrypoint',
    package: '@memstack/github',
    version: '2.4.1',
    kind: 'mcp',
    providers: ['github'],
    skills: ['pull-request-review'],
    enabled: true,
    discovered: true,
    schema_supported: true,
    config_schema: {
      type: 'object',
      required: ['repository', 'access_token'],
      properties: {
        repository: {
          type: 'string',
          title: 'Repository',
          description: 'owner/repository',
        },
        access_token: { type: 'string' },
        sync_interval: { type: 'integer', minimum: 1, maximum: 60 },
        include_drafts: {
          type: 'boolean',
          title: 'Include draft pull requests',
        },
        review_mode: {
          type: 'string',
          enum: ['safe', 'fast'],
          title: 'Review mode',
        },
      },
    },
    config_ui_hints: {
      access_token: { label: 'Access token', sensitive: true },
      sync_interval: { label: 'Sync interval (minutes)' },
    },
    defaults: { sync_interval: 10, include_drafts: false, review_mode: 'safe' },
    secret_paths: ['access_token'],
  },
  slack: {
    plugin_name: 'slack',
    providers: ['slack'],
    skills: ['incident-triage'],
    enabled: true,
    discovered: true,
    schema_supported: true,
    config_schema: {
      type: 'object',
      properties: { workspace: { type: 'string' } },
    },
    secret_paths: [],
  },
  'release-notifier': {
    plugin_name: 'release-notifier',
    providers: ['webhook'],
    skills: ['release-notification'],
    enabled: true,
    discovered: true,
    schema_supported: true,
    config_schema: {
      type: 'object',
      required: ['endpoint', 'token'],
      properties: {
        endpoint: { type: 'string', title: 'Webhook endpoint' },
        token: { type: 'string' },
        retries: { type: 'integer', minimum: 0, maximum: 10 },
        enabled: { type: 'boolean', title: 'Send release notifications' },
        mode: {
          type: 'string',
          enum: ['safe', 'fast'],
          title: 'Delivery mode',
        },
      },
    },
    config_ui_hints: { token: { label: 'Access token', sensitive: true } },
    defaults: { retries: 3, enabled: true, mode: 'safe' },
    secret_paths: ['token'],
  },
};

let pluginConfigs: Record<string, PluginConfigRecord> = {
  github: {
    tenant_id: QA_TENANT_ID,
    plugin_name: 'github',
    config: {
      repository: 'memstack/agi-stack',
      access_token: '__MEMSTACK_SECRET_UNCHANGED__',
      sync_interval: 10,
      include_drafts: false,
      review_mode: 'safe',
    },
    updated_at: NOW,
  },
  slack: {
    tenant_id: QA_TENANT_ID,
    plugin_name: 'slack',
    config: { workspace: 'northstar' },
    updated_at: NOW,
  },
};

const channelCatalog: ManagedChannelPluginCatalogItem[] = [
  {
    channel_type: 'slack',
    plugin_name: 'slack',
    source: 'entrypoint',
    package: '@memstack/slack',
    version: '3.2.0',
    enabled: true,
    discovered: true,
    schema_supported: true,
  },
];

const channelSchemas: Record<string, ManagedChannelPluginConfigSchema> = {
  slack: {
    channel_type: 'slack',
    plugin_name: 'slack',
    source: 'entrypoint',
    package: '@memstack/slack',
    version: '3.2.0',
    schema_supported: true,
    config_schema: {
      type: 'object',
      required: ['bot_token', 'connection_mode'],
      properties: {
        bot_token: { type: 'string', title: 'Bot token' },
        connection_mode: { type: 'string', enum: ['websocket', 'webhook'] },
        mention_required: { type: 'boolean', title: 'Require mention' },
      },
    },
    config_ui_hints: { bot_token: { label: 'Bot token', sensitive: true } },
    defaults: { connection_mode: 'websocket', mention_required: true },
    secret_paths: ['bot_token'],
  },
};

let channelConfigs: ManagedChannelConfig[] = [
  {
    id: 'channel-slack-alerts',
    project_id: QA_PROJECT_ID,
    channel_type: 'slack',
    name: 'Incident alerts',
    enabled: true,
    connection_mode: 'websocket',
    extra_settings: {
      bot_token: '__MEMSTACK_SECRET_UNCHANGED__',
      mention_required: true,
    },
    dm_policy: 'open',
    group_policy: 'open',
    rate_limit_per_minute: 60,
    status: 'connected',
    description: 'Production incident routing',
    created_at: NOW,
    updated_at: NOW,
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

let subagents: ManagedSubAgent[] = [
  {
    id: 'subagent-release-reviewer',
    tenant_id: QA_TENANT_ID,
    project_id: QA_PROJECT_ID,
    name: 'release-reviewer',
    display_name: 'Release reviewer',
    system_prompt: 'Internal delegation policy must never be rendered or searched.',
    trigger: {
      description: 'Reviews release readiness and delivery evidence.',
      keywords: ['release', 'readiness'],
      examples: ['Review this release candidate'],
    },
    model: 'openai/gpt-5.1',
    enabled: true,
    source: 'database',
    allowed_tools: ['read', 'git_diff', 'run_tests'],
    allowed_skills: ['code-verification'],
    allowed_mcp_servers: ['github'],
    fallback_models: ['anthropic/claude-sonnet-4-5'],
    total_invocations: 18,
    success_rate: 0.94,
    avg_execution_time_ms: 1250,
    updated_at: NOW,
  },
  {
    id: 'subagent-filesystem-researcher',
    tenant_id: QA_TENANT_ID,
    project_id: null,
    name: 'filesystem-researcher',
    display_name: 'Research specialist',
    trigger: {
      description: 'Collects verified evidence from governed sources.',
    },
    model: 'anthropic/claude-sonnet-4-5',
    enabled: false,
    source: 'filesystem',
    allowed_tools: ['web_search', 'browser'],
    allowed_skills: ['competitive-research'],
    allowed_mcp_servers: [],
    fallback_models: [],
    total_invocations: 0,
    success_rate: 0,
    avg_execution_time_ms: 0,
    updated_at: '2026-07-10T04:10:00.000Z',
  },
];

const subagentTemplates: ManagedSubAgentTemplate[] = [
  {
    id: 'template-incident-commander',
    tenant_id: QA_TENANT_ID,
    name: 'incident-commander',
    version: '1.2.0',
    display_name: 'Incident commander',
    description: 'Coordinates evidence, owners, and recovery actions during an incident.',
    category: 'operations',
    tags: ['incident', 'recovery'],
    system_prompt: 'Coordinate the incident response using verified evidence.',
    trigger_description: 'Use for active service incidents.',
    trigger_keywords: ['incident', 'outage'],
    trigger_examples: ['Coordinate this production incident'],
    model: 'inherit',
    max_tokens: 4096,
    temperature: 0.4,
    max_iterations: 12,
    allowed_tools: ['read', 'terminal'],
    author: 'MemStack',
    is_builtin: true,
    is_published: true,
    install_count: 21,
    rating: 4.9,
    metadata: null,
    created_at: NOW,
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

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function packageField(content: string, field: string): string {
  const prefix = `${field}:`;
  const line = content
    .split(/\r?\n/)
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));
  return line ? line.slice(prefix.length).trim().replace(/^['"]|['"]$/g, '') : '';
}

function importedSkill(
  name: string,
  content: string,
  projectId: string | null,
  current?: ManagedSkill
): ManagedSkill {
  const versionNumber = (current?.current_version ?? 0) + 1;
  return {
    ...(current ?? {}),
    id: current?.id ?? name,
    tenant_id: QA_TENANT_ID,
    project_id: projectId,
    name,
    description:
      packageField(content, 'description') || current?.description || 'Imported Skill package.',
    status: current?.status ?? 'active',
    scope: projectId ? 'project' : 'tenant',
    tools: current?.tools ?? [],
    full_content: content,
    metadata: current?.metadata ?? {},
    spec_version: current?.spec_version ?? '1.0',
    current_version: versionNumber,
    version_label: packageField(content, 'version') || current?.version_label || null,
    is_system_skill: false,
    updated_at: NOW,
  };
}

function snapshotImportedSkill(
  skill: ManagedSkill,
  changeSummary: string,
  createdBy: string
): ManagedSkillVersion {
  const versionNumber = skill.current_version ?? 1;
  return {
    id: `${skill.id}-v${versionNumber}-${crypto.randomUUID()}`,
    skill_id: skill.id,
    version_number: versionNumber,
    version_label: skill.version_label ?? null,
    change_summary: changeSummary || null,
    created_by: createdBy,
    created_at: NOW,
  };
}

function qaEvolutionDetail(skill: ManagedSkill): ManagedSkillEvolutionDetail {
  const jobs = skillEvolutionJobs.filter((job) => job.skill_name === skill.name);
  const jobRoute = jobs.map((job) => ({
    kind: 'evolution_job' as const,
    id: job.id,
    label: `Evolution ${job.action}`,
    project_id: job.project_id,
    status: job.status,
    action: job.action,
    version_number: null,
    version_label: null,
    skill_version_id: job.skill_version_id,
    change_summary: null,
    rationale: job.rationale,
    candidate_preview: job.candidate_preview,
    created_by: null,
    created_at: job.created_at,
  }));
  const versionRoute = (skillVersions[skill.id] ?? []).map((version) => ({
    kind: 'version' as const,
    id: version.id,
    label: version.version_label || `#${version.version_number}`,
    project_id: skill.project_id ?? null,
    status: null,
    action: null,
    version_number: version.version_number,
    version_label: version.version_label,
    skill_version_id: version.id,
    change_summary: version.change_summary,
    rationale: null,
    candidate_preview: null,
    created_by: version.created_by,
    created_at: version.created_at,
  }));
  return {
    skill_id: skill.id,
    skill_name: skill.name,
    captured_session_count: skill.name === 'competitive-research' ? 12 : 3,
    jobs,
    route: [...jobRoute, ...versionRoute],
    trigger: {
      capture_hook: 'session_complete',
      capture_timing: 'After every completed session',
      scheduled_timing: 'Every 60 minutes',
      manual_trigger: `/skills/${skill.id}/evolution/run`,
      min_sessions_per_skill: 5,
      scoring_min_sessions_per_skill: 3,
      min_avg_score: 0.8,
      max_sessions_per_batch: 20,
      publish_mode: 'review',
      auto_apply: false,
      enabled: true,
    },
  };
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function agentFromBody(
  body: Record<string, unknown>,
  current?: ManagedAgentDefinition
): ManagedAgentDefinition {
  const trigger = current?.trigger;
  const currentTrigger =
    trigger && typeof trigger === 'object' && !Array.isArray(trigger)
      ? (trigger as Record<string, unknown>)
      : {};
  const name = stringValue(body.name, current?.name ?? 'new_agent');
  return {
    ...current,
    id: current?.id ?? `agent-${name}`,
    tenant_id: QA_TENANT_ID,
    project_id:
      typeof body.project_id === 'string' || body.project_id === null
        ? body.project_id
        : (current?.project_id ?? null),
    name,
    display_name: stringValue(body.display_name, current?.display_name ?? name),
    system_prompt: stringValue(body.system_prompt, current?.system_prompt ?? ''),
    trigger: {
      description: stringValue(
        body.trigger_description,
        stringValue(currentTrigger.description, 'Default agent trigger')
      ),
      keywords: stringArray(body.trigger_keywords, stringArray(currentTrigger.keywords)),
      examples: stringArray(body.trigger_examples, stringArray(currentTrigger.examples)),
    },
    model: stringValue(body.model, stringValue(current?.model, 'inherit')),
    temperature: numberValue(body.temperature, numberValue(current?.temperature, 0.7)),
    max_tokens: numberValue(body.max_tokens, numberValue(current?.max_tokens, 4096)),
    max_iterations: numberValue(body.max_iterations, numberValue(current?.max_iterations, 10)),
    allowed_tools: stringArray(body.allowed_tools, current?.allowed_tools ?? []),
    allowed_skills: stringArray(body.allowed_skills, current?.allowed_skills ?? []),
    allowed_mcp_servers: stringArray(body.allowed_mcp_servers, current?.allowed_mcp_servers ?? []),
    fallback_models: stringArray(body.fallback_models, stringArray(current?.fallback_models)),
    can_spawn: booleanValue(body.can_spawn, booleanValue(current?.can_spawn, false)),
    max_spawn_depth: numberValue(body.max_spawn_depth, numberValue(current?.max_spawn_depth, 3)),
    agent_to_agent_enabled: booleanValue(
      body.agent_to_agent_enabled,
      booleanValue(current?.agent_to_agent_enabled, false)
    ),
    agent_to_agent_allowlist: stringArray(
      body.agent_to_agent_allowlist,
      stringArray(current?.agent_to_agent_allowlist)
    ),
    discoverable: booleanValue(body.discoverable, booleanValue(current?.discoverable, true)),
    max_retries: numberValue(body.max_retries, numberValue(current?.max_retries, 0)),
    source: current?.source ?? 'database',
    enabled: current?.enabled ?? true,
    status: current?.status ?? 'active',
    updated_at: NOW,
  };
}

function subagentFromBody(
  body: Record<string, unknown>,
  current?: ManagedSubAgent,
): ManagedSubAgent {
  const currentTrigger =
    current?.trigger && typeof current.trigger === 'object' ? current.trigger : {};
  const name = stringValue(body.name, current?.name ?? 'new_subagent');
  return {
    ...current,
    id: current?.id ?? `subagent-${name}`,
    tenant_id: QA_TENANT_ID,
    project_id:
      typeof body.project_id === 'string' || body.project_id === null
        ? body.project_id
        : (current?.project_id ?? null),
    name,
    display_name: stringValue(body.display_name, current?.display_name ?? name),
    system_prompt: stringValue(body.system_prompt, current?.system_prompt ?? ''),
    trigger: {
      description: stringValue(
        body.trigger_description,
        stringValue(currentTrigger.description, 'Use for delegated specialist work.'),
      ),
      keywords: stringArray(body.trigger_keywords, stringArray(currentTrigger.keywords)),
      examples: stringArray(body.trigger_examples, stringArray(currentTrigger.examples)),
    },
    model: stringValue(body.model, current?.model ?? 'inherit'),
    color: stringValue(body.color, current?.color ?? 'blue'),
    allowed_tools: stringArray(body.allowed_tools, current?.allowed_tools ?? []),
    allowed_skills: stringArray(body.allowed_skills, current?.allowed_skills ?? []),
    allowed_mcp_servers: stringArray(
      body.allowed_mcp_servers,
      current?.allowed_mcp_servers ?? [],
    ),
    max_tokens: numberValue(body.max_tokens, current?.max_tokens ?? 4096),
    temperature: numberValue(body.temperature, current?.temperature ?? 0.7),
    max_iterations: numberValue(body.max_iterations, current?.max_iterations ?? 10),
    enabled: current?.enabled ?? true,
    source: 'database',
    total_invocations: current?.total_invocations ?? 0,
    success_rate: current?.success_rate ?? 0,
    avg_execution_time_ms: current?.avg_execution_time_ms ?? 0,
    created_at: current?.created_at ?? NOW,
    updated_at: NOW,
  };
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
    provider.provider_type
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
    models.has(target.model_id)
  );
}

function safeProviderFromBody(
  body: Record<string, unknown>,
  current?: ManagedLlmProvider
): ManagedLlmProvider {
  const nextRevision = (current?.revision ?? 0) + 1;
  const apiKeySubmitted = Boolean(stringValue(body.api_key).trim());
  const rawAuthMethod = stringValue(body.auth_method, current?.auth_method ?? 'api_key');
  const authMethod: LlmProviderAuthMethod = ['api_key', 'environment', 'none'].includes(
    rawAuthMethod
  )
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
          : 'application_vault',
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
  if (method === 'POST' && path === '/api/v1/skills/') {
    const payload = readJsonBody(body);
    const name = stringValue(payload.name).trim();
    if (!name) return jsonResponse({ detail: 'Skill name is required.' }, 422);
    if (skills.some((skill) => skill.name === name)) {
      return jsonResponse({ detail: 'Skill already exists.' }, 409);
    }
    const created: ManagedSkill = {
      id: name,
      tenant_id: QA_TENANT_ID,
      project_id: stringValue(payload.project_id) || null,
      name,
      description: stringValue(payload.description),
      status: 'active',
      scope: stringValue(payload.scope) || 'tenant',
      tools: stringArray(payload.tools, ['*']),
      full_content: stringValue(payload.full_content) || null,
      metadata: recordValue(payload.metadata),
      license: stringValue(payload.license) || null,
      compatibility: stringValue(payload.compatibility) || null,
      allowed_tools_raw: stringValue(payload.allowed_tools_raw) || null,
      spec_version: stringValue(payload.spec_version) || '1.0',
      current_version: 0,
      is_system_skill: false,
      updated_at: NOW,
    };
    skills = [created, ...skills];
    return jsonResponse(created);
  }
  if (method === 'POST' && path === '/api/v1/skills/import') {
    const payload = readJsonBody(body);
    const content = stringValue(payload.skill_md_content);
    const name = packageField(content, 'name');
    if (!name) return jsonResponse({ detail: 'SKILL.md name is required.' }, 422);
    const current = skills.find((item) => item.name === name);
    if (current && payload.overwrite !== true) {
      return jsonResponse({ detail: 'Skill already exists.' }, 409);
    }
    const projectId = stringValue(payload.project_id) || null;
    const next = importedSkill(name, content, projectId, current);
    skills = current
      ? skills.map((item) => (item.id === current.id ? next : item))
      : [next, ...skills];
    const version = snapshotImportedSkill(
      next,
      stringValue(payload.change_summary),
      'import'
    );
    skillVersions[next.id] = [version, ...(skillVersions[next.id] ?? [])];
    return jsonResponse(
      {
        action: current ? 'update' : 'import',
        skill: next,
        version_number: version.version_number,
        version_label: version.version_label,
      },
      201
    );
  }
  if (method === 'POST' && path === '/api/v1/skills/import/zip') {
    const form = body instanceof FormData ? body : null;
    const archive = form?.get('archive');
    if (!(archive instanceof File)) {
      return jsonResponse({ detail: 'Skill ZIP archive is required.' }, 422);
    }
    const baseName = archive.name.replace(/\.zip$/i, '').toLowerCase();
    const name = baseName.replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'imported-skill';
    const current = skills.find((item) => item.name === name);
    if (current && form?.get('overwrite') !== 'true') {
      return jsonResponse({ detail: 'Skill already exists.' }, 409);
    }
    const projectId = stringValue(form?.get('project_id')) || null;
    const content = `---\nname: ${name}\ndescription: Imported from ${archive.name}\n---\n\n# ${name}\n`;
    const next = importedSkill(name, content, projectId, current);
    skills = current
      ? skills.map((item) => (item.id === current.id ? next : item))
      : [next, ...skills];
    const version = snapshotImportedSkill(
      next,
      stringValue(form?.get('change_summary')),
      'import'
    );
    skillVersions[next.id] = [version, ...(skillVersions[next.id] ?? [])];
    return jsonResponse(
      {
        action: current ? 'update' : 'import',
        skill: next,
        version_number: version.version_number,
        version_label: version.version_label,
      },
      201
    );
  }
  if (method === 'GET' && path.endsWith('/plugins')) {
    return jsonResponse({ plugins });
  }

  if (method === 'POST' && path.endsWith('/plugins/install')) {
    const requirement = stringValue(readJsonBody(body).requirement).trim();
    if (!requirement) return jsonResponse({ detail: 'Package requirement is required.' }, 422);
    if (!plugins.some((plugin) => plugin.name === 'release-notifier')) {
      plugins = [
        {
          name: 'release-notifier',
          source: 'entrypoint',
          package: requirement,
          version: '2.0.0',
          kind: 'service',
          enabled: true,
          discovered: true,
          providers: ['webhook'],
          skills: ['release-notification'],
          channel_types: ['release_events'],
          tool_definitions: [{ name: 'notify_release' }],
          schema_supported: true,
          updated_at: NOW,
        },
        ...plugins,
      ];
    }
    pluginConfigs['release-notifier'] ??= {
      tenant_id: QA_TENANT_ID,
      plugin_name: 'release-notifier',
      config: { retries: 3, enabled: true, mode: 'safe' },
      updated_at: NOW,
    };
    return jsonResponse({ success: true, message: 'Plugin installed.' });
  }

  if (method === 'POST' && path.endsWith('/plugins/reload')) {
    return jsonResponse({ success: true, message: 'Plugin runtime reloaded.' });
  }

  const pluginConfigSchemaMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/([^/]+)\/config-schema$/
  );
  if (method === 'GET' && pluginConfigSchemaMatch) {
    const pluginName = decodeURIComponent(pluginConfigSchemaMatch[1]);
    const schema = pluginSchemas[pluginName];
    return schema
      ? jsonResponse(schema)
      : jsonResponse({ detail: 'Plugin config schema not found.' }, 404);
  }

  const pluginConfigMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/([^/]+)\/config$/
  );
  if (pluginConfigMatch) {
    const pluginName = decodeURIComponent(pluginConfigMatch[1]);
    const current = pluginConfigs[pluginName] ?? {
      tenant_id: QA_TENANT_ID,
      plugin_name: pluginName,
      config: {},
    };
    if (method === 'GET') return jsonResponse(current);
    if (method === 'PUT') {
      const nextConfig = readJsonBody(body).config;
      if (!nextConfig || typeof nextConfig !== 'object' || Array.isArray(nextConfig)) {
        return jsonResponse({ detail: 'Plugin config is invalid.' }, 422);
      }
      pluginConfigs = {
        ...pluginConfigs,
        [pluginName]: {
          ...current,
          config: {
            ...current.config,
            ...(nextConfig as Record<string, unknown>),
          },
          updated_at: NOW,
        },
      };
      return jsonResponse(pluginConfigs[pluginName]);
    }
  }

  if (
    method === 'GET' &&
    path === `/api/v1/channels/tenants/${QA_TENANT_ID}/plugins/channel-catalog`
  ) {
    return jsonResponse({ items: channelCatalog });
  }
  const channelSchemaMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/channel-catalog\/([^/]+)\/schema$/
  );
  if (method === 'GET' && channelSchemaMatch) {
    const schema = channelSchemas[decodeURIComponent(channelSchemaMatch[1])];
    return schema ? jsonResponse(schema) : jsonResponse({ detail: 'Schema not found.' }, 404);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/channels/projects/${QA_PROJECT_ID}/configs`
  ) {
    return jsonResponse({ items: channelConfigs, total: channelConfigs.length });
  }
  if (
    method === 'POST' &&
    path === `/api/v1/channels/projects/${QA_PROJECT_ID}/configs`
  ) {
    const payload = readJsonBody(body);
    const channelType = stringValue(payload.channel_type);
    const created: ManagedChannelConfig = {
      id: `channel-${channelType}-${channelConfigs.length + 1}`,
      project_id: QA_PROJECT_ID,
      channel_type: channelType,
      name: stringValue(payload.name),
      enabled: booleanValue(payload.enabled, true),
      connection_mode:
        payload.connection_mode === 'webhook' ? 'webhook' : 'websocket',
      extra_settings: recordValue(payload.extra_settings),
      dm_policy: 'open',
      group_policy: 'open',
      rate_limit_per_minute: 60,
      status: 'disconnected',
      description: stringValue(payload.description),
      created_at: NOW,
      updated_at: NOW,
    };
    channelConfigs = [created, ...channelConfigs];
    return jsonResponse(created, 201);
  }
  const channelTestMatch = path.match(/^\/api\/v1\/channels\/configs\/([^/]+)\/test$/);
  if (method === 'POST' && channelTestMatch) {
    const channelId = decodeURIComponent(channelTestMatch[1]);
    channelConfigs = channelConfigs.map((channel) =>
      channel.id === channelId ? { ...channel, status: 'connected' } : channel
    );
    return jsonResponse({ success: true, message: 'Connection succeeded.' });
  }
  const channelConfigMatch = path.match(/^\/api\/v1\/channels\/configs\/([^/]+)$/);
  if (channelConfigMatch) {
    const channelId = decodeURIComponent(channelConfigMatch[1]);
    const current = channelConfigs.find((channel) => channel.id === channelId);
    if (!current) return jsonResponse({ detail: 'Channel not found.' }, 404);
    if (method === 'PUT') {
      const payload = readJsonBody(body);
      const updated: ManagedChannelConfig = {
        ...current,
        ...(typeof payload.name === 'string' ? { name: payload.name } : {}),
        ...(typeof payload.enabled === 'boolean' ? { enabled: payload.enabled } : {}),
        ...(payload.connection_mode === 'websocket' || payload.connection_mode === 'webhook'
          ? { connection_mode: payload.connection_mode }
          : {}),
        ...(typeof payload.description === 'string' ? { description: payload.description } : {}),
        ...(payload.extra_settings ? { extra_settings: recordValue(payload.extra_settings) } : {}),
        updated_at: NOW,
      };
      channelConfigs = channelConfigs.map((channel) =>
        channel.id === channelId ? updated : channel
      );
      return jsonResponse(updated);
    }
    if (method === 'DELETE') {
      channelConfigs = channelConfigs.filter((channel) => channel.id !== channelId);
      return new Response(null, { status: 204 });
    }
  }

  const pluginUninstallMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/([^/]+)\/uninstall$/
  );
  if (method === 'POST' && pluginUninstallMatch) {
    const pluginName = decodeURIComponent(pluginUninstallMatch[1]);
    plugins = plugins.filter((plugin) => plugin.name !== pluginName);
    const { [pluginName]: _removed, ...remainingConfigs } = pluginConfigs;
    pluginConfigs = remainingConfigs;
    return jsonResponse({ success: true, message: 'Plugin uninstalled.' });
  }
  if (method === 'GET' && path === '/api/v1/agent/definitions') {
    return jsonResponse({ definitions: agents });
  }
  if (method === 'POST' && path === '/api/v1/agent/definitions') {
    const created = agentFromBody(readJsonBody(body));
    agents = [created, ...agents];
    return jsonResponse(created, 201);
  }
  if (method === 'POST' && path === '/api/v1/subagents/') {
    const created = subagentFromBody(readJsonBody(body));
    subagents = [created, ...subagents];
    return jsonResponse(created, 201);
  }
  if (method === 'GET' && path === '/api/v1/subagents/') {
    return jsonResponse({ subagents, total: subagents.length });
  }
  if (method === 'GET' && path === '/api/v1/subagents/templates/list') {
    return jsonResponse({ templates: subagentTemplates, total: subagentTemplates.length });
  }
  const subagentTemplateInstallMatch = path.match(
    /^\/api\/v1\/subagents\/templates\/([^/]+)\/install$/
  );
  if (method === 'POST' && subagentTemplateInstallMatch) {
    const templateId = decodeURIComponent(subagentTemplateInstallMatch[1]);
    const template = subagentTemplates.find((item) => item.id === templateId);
    if (!template) return jsonResponse({ detail: 'Template not found.' }, 404);
    const created: ManagedSubAgent = {
      id: `subagent-${template.name}`,
      tenant_id: QA_TENANT_ID,
      project_id: null,
      name: template.name,
      display_name: template.display_name,
      system_prompt: template.system_prompt,
      trigger: {
        description: template.trigger_description || template.name,
        keywords: template.trigger_keywords,
        examples: template.trigger_examples,
      },
      model: template.model,
      enabled: true,
      source: 'database',
      allowed_tools: template.allowed_tools,
      total_invocations: 0,
      success_rate: 0,
      avg_execution_time_ms: 0,
      updated_at: NOW,
    };
    subagents = [created, ...subagents];
    return jsonResponse(created, 201);
  }
  const filesystemSubagentImportMatch = path.match(
    /^\/api\/v1\/subagents\/filesystem\/([^/]+)\/import$/
  );
  if (method === 'POST' && filesystemSubagentImportMatch) {
    const name = decodeURIComponent(filesystemSubagentImportMatch[1]);
    const existing = subagents.find((item) => item.name === name && item.source === 'filesystem');
    if (!existing) return jsonResponse({ detail: 'Filesystem SubAgent not found.' }, 404);
    const created = {
      ...existing,
      id: `subagent-imported-${name}`,
      project_id: url.searchParams.get('project_id'),
      source: 'database' as const,
    };
    subagents = subagents.map((item) => (item.id === existing.id ? created : item));
    return jsonResponse(created, 201);
  }
  const managedSubagentMatch = path.match(/^\/api\/v1\/subagents\/([^/]+)$/);
  if (managedSubagentMatch) {
    const subagentId = decodeURIComponent(managedSubagentMatch[1]);
    const current = subagents.find((item) => item.id === subagentId);
    if (!current) return jsonResponse({ detail: 'SubAgent not found.' }, 404);
    if (method === 'PUT') {
      const updated = subagentFromBody(readJsonBody(body), current);
      subagents = subagents.map((item) => (item.id === subagentId ? updated : item));
      return jsonResponse(updated);
    }
    if (method === 'DELETE') {
      subagents = subagents.filter((item) => item.id !== subagentId);
      return new Response(null, { status: 204 });
    }
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
        JSON.stringify([target.provider_id, target.model_id])
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

  const discoveryMatch = path.match(/^\/api\/v1\/llm-providers\/([^/]+)\/models\/discover$/);
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
        (authMethod === 'environment' && QA_ENVIRONMENT_SECRETS.has(environmentVariable)))
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

  const skillExportMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/export$/);
  if (method === 'GET' && skillExportMatch) {
    const exportId = decodeURIComponent(skillExportMatch[1]);
    const skill = skills.find((item) => item.id === exportId || item.name === exportId);
    if (!skill) return jsonResponse({ detail: 'Skill not found.' }, 404);
    return jsonResponse({
      format: 'agentskills.io/skill-package',
      skill,
      skill_md_content: skill.full_content ?? '',
      resource_files: { 'references/qa.md': 'Desktop export validation.' },
      version_number: skill.current_version ?? null,
      version_label: skill.version_label ?? null,
    });
  }

  const skillVersionDetailMatch = path.match(
    /^\/api\/v1\/skills\/([^/]+)\/versions\/(\d+)$/
  );
  if (method === 'GET' && skillVersionDetailMatch) {
    const skillId = decodeURIComponent(skillVersionDetailMatch[1]);
    const versionNumber = Number(skillVersionDetailMatch[2]);
    const version = (skillVersions[skillId] ?? []).find(
      (candidate) => candidate.version_number === versionNumber
    );
    const skill = skills.find((item) => item.id === skillId);
    if (!version || !skill) return jsonResponse({ detail: 'Skill version not found.' }, 404);
    return jsonResponse({
      ...version,
      skill_md_content: `${skill.full_content ?? ''}\n\n<!-- snapshot ${versionNumber} -->`,
      resource_files: { 'references/qa.md': `Version ${versionNumber}` },
    });
  }

  const evolutionJobMatch = path.match(
    /^\/api\/v1\/skills\/evolution\/jobs\/([^/]+)\/(apply|reject)$/
  );
  if (method === 'POST' && evolutionJobMatch) {
    const jobId = decodeURIComponent(evolutionJobMatch[1]);
    const action = evolutionJobMatch[2];
    const job = skillEvolutionJobs.find((candidate) => candidate.id === jobId);
    if (!job || job.status !== 'pending_review') {
      return jsonResponse({ detail: 'Evolution job is not pending review.' }, 400);
    }
    const nextJob: ManagedSkillEvolutionJob = {
      ...job,
      status: action === 'apply' ? 'applied' : 'rejected',
      blocked_by_review: false,
      applied_at: action === 'apply' ? NOW : null,
    };
    skillEvolutionJobs = skillEvolutionJobs.map((candidate) =>
      candidate.id === jobId ? nextJob : candidate
    );
    if (action === 'apply') {
      const skill = skills.find((candidate) => candidate.name === job.skill_name);
      if (skill) {
        const updated = { ...skill, current_version: (skill.current_version ?? 0) + 1 };
        skills = skills.map((candidate) => (candidate.id === skill.id ? updated : candidate));
        const version = snapshotImportedSkill(updated, 'Applied evolution candidate', 'evolution');
        skillVersions[skill.id] = [version, ...(skillVersions[skill.id] ?? [])];
        nextJob.skill_version_id = version.id;
      }
    }
    return jsonResponse(nextJob);
  }

  const skillEvolutionRunMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/evolution\/run$/);
  if (method === 'POST' && skillEvolutionRunMatch) {
    const skillId = decodeURIComponent(skillEvolutionRunMatch[1]);
    const skill = skills.find((candidate) => candidate.id === skillId);
    if (!skill) return jsonResponse({ detail: 'Skill not found.' }, 404);
    const job: ManagedSkillEvolutionJob = {
      id: `${skill.id}-evolution-${crypto.randomUUID()}`,
      project_id: skill.project_id ?? null,
      skill_name: skill.name,
      action: 'update',
      status: 'pending_review',
      rationale: 'Manual Desktop evolution validation.',
      candidate_preview: 'Clarify the validation steps before publishing.',
      candidate_content: '# Candidate\n\nClarify the validation steps before publishing.',
      blocked_by_review: true,
      session_ids: ['session-manual'],
      skill_version_id: null,
      created_at: NOW,
      applied_at: null,
    };
    skillEvolutionJobs = [job, ...skillEvolutionJobs];
    return jsonResponse({ skill_id: skill.id, skill_name: skill.name, result: { queued: true } });
  }

  const skillEvolutionMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/evolution$/);
  if (method === 'GET' && skillEvolutionMatch) {
    const skillId = decodeURIComponent(skillEvolutionMatch[1]);
    const skill = skills.find((candidate) => candidate.id === skillId);
    if (!skill) return jsonResponse({ detail: 'Skill not found.' }, 404);
    return jsonResponse(qaEvolutionDetail(skill));
  }

  const skillVersionsMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/versions$/);
  if (method === 'GET' && skillVersionsMatch) {
    const skillId = decodeURIComponent(skillVersionsMatch[1]);
    const versions = skillVersions[skillId] ?? [];
    return jsonResponse({ versions, total: versions.length });
  }

  const skillRollbackMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/rollback$/);
  if (method === 'POST' && skillRollbackMatch) {
    const skillId = decodeURIComponent(skillRollbackMatch[1]);
    const current = skills.find((item) => item.id === skillId);
    if (!current) return jsonResponse({ detail: 'Skill not found.' }, 404);
    const versionNumber = numberValue(readJsonBody(body).version_number, 0);
    const target = (skillVersions[skillId] ?? []).find(
      (version) => version.version_number === versionNumber
    );
    if (!target) return jsonResponse({ detail: 'Skill version not found.' }, 400);
    const updated: ManagedSkill = {
      ...current,
      current_version: (current.current_version ?? 0) + 1,
      version_label: target.version_label,
      updated_at: NOW,
    };
    skills = skills.map((item) => (item.id === skillId ? updated : item));
    const snapshot = snapshotImportedSkill(
      updated,
      `Rollback to version ${versionNumber}`,
      'rollback'
    );
    skillVersions[skillId] = [snapshot, ...(skillVersions[skillId] ?? [])];
    return jsonResponse(updated);
  }

  const skillContentMatch = path.match(/^\/api\/v1\/skills\/([^/]+)\/content$/);
  if (skillContentMatch) {
    const skillId = decodeURIComponent(skillContentMatch[1]);
    const skill = skills.find((item) => item.id === skillId);
    if (!skill) return jsonResponse({ detail: 'Skill not found.' }, 404);
    if (method === 'GET') {
      return jsonResponse({
        skill_id: skill.id,
        name: skill.name,
        full_content: skill.full_content ?? null,
        scope: skill.scope,
        is_system_skill: skill.is_system_skill ?? false,
      });
    }
    if (method === 'PUT') {
      const fullContent = stringValue(readJsonBody(body).full_content);
      skills = skills.map((item) =>
        item.id === skillId ? { ...item, full_content: fullContent, updated_at: NOW } : item
      );
      return jsonResponse(skills.find((item) => item.id === skillId) ?? null);
    }
  }

  const skillMatch = path.match(/^\/api\/v1\/skills\/([^/]+)$/);
  if (skillMatch) {
    const skillId = decodeURIComponent(skillMatch[1]);
    const current = skills.find((item) => item.id === skillId);
    if (!current) return jsonResponse({ detail: 'Skill not found.' }, 404);
    if (method === 'PUT') {
      const payload = readJsonBody(body);
      const updated: ManagedSkill = {
        ...current,
        name: stringValue(payload.name) || current.name,
        description: stringValue(payload.description) || current.description,
        tools: stringArray(payload.tools, current.tools),
        metadata: recordValue(payload.metadata),
        license: stringValue(payload.license) || null,
        compatibility: stringValue(payload.compatibility) || null,
        allowed_tools_raw: stringValue(payload.allowed_tools_raw) || null,
        spec_version: stringValue(payload.spec_version) || '1.0',
        updated_at: NOW,
      };
      skills = skills.map((item) => (item.id === skillId ? updated : item));
      return jsonResponse(updated);
    }
    if (method === 'DELETE') {
      skills = skills.filter((item) => item.id !== skillId);
      return new Response(null, { status: 204 });
    }
  }

  const pluginStatusMatch = path.match(
    /^\/api\/v1\/channels\/tenants\/[^/]+\/plugins\/([^/]+)\/(enable|disable)$/
  );
  if (method === 'POST' && pluginStatusMatch) {
    const pluginName = decodeURIComponent(pluginStatusMatch[1]);
    const enabled = pluginStatusMatch[2] === 'enable';
    plugins = plugins.map((plugin) =>
      plugin.name === pluginName ? { ...plugin, enabled } : plugin
    );
    return jsonResponse(plugins.find((plugin) => plugin.name === pluginName) ?? null);
  }

  const agentStatusMatch = path.match(/^\/api\/v1\/agent\/definitions\/([^/]+)\/enabled$/);
  if (method === 'PATCH' && agentStatusMatch) {
    const agentId = decodeURIComponent(agentStatusMatch[1]);
    const enabled = booleanValue(readJsonBody(body).enabled, false);
    agents = agents.map((agent) =>
      agent.id === agentId ? { ...agent, enabled, status: enabled ? 'active' : 'disabled' } : agent
    );
    return jsonResponse(agents.find((agent) => agent.id === agentId) ?? null);
  }

  const agentDefinitionMatch = path.match(/^\/api\/v1\/agent\/definitions\/([^/]+)$/);
  if (agentDefinitionMatch) {
    const agentId = decodeURIComponent(agentDefinitionMatch[1]);
    const current = agents.find((agent) => agent.id === agentId);
    if (!current) return jsonResponse({ detail: 'Definition not found.' }, 404);
    if (method === 'PUT') {
      const updated = agentFromBody(readJsonBody(body), current);
      agents = agents.map((agent) => (agent.id === agentId ? updated : agent));
      return jsonResponse(updated);
    }
    if (method === 'DELETE') {
      agents = agents.filter((agent) => agent.id !== agentId);
      return jsonResponse({ deleted: true, id: agentId });
    }
  }

  const subagentStatusMatch = path.match(/^\/api\/v1\/subagents\/([^/]+)\/enable$/);
  if (method === 'PATCH' && subagentStatusMatch) {
    const subagentId = decodeURIComponent(subagentStatusMatch[1]);
    const enabled = url.searchParams.get('enabled') === 'true';
    subagents = subagents.map((subagent) =>
      subagent.id === subagentId ? { ...subagent, enabled } : subagent
    );
    return jsonResponse(subagents.find((subagent) => subagent.id === subagentId) ?? null);
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
        : item
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
  const searchParams = new URLSearchParams(window.location.search);
  const [config, setConfig] = useState<DesktopRuntimeConfig>(() => ({
    ...qaConfig,
    mode: searchParams.get('mode') === 'cloud' ? 'cloud' : qaConfig.mode,
  }));
  const requestedSection = searchParams.get('section');
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
    'subagents',
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
  </React.StrictMode>
);
