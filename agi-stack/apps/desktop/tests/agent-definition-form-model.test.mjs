import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  agentDefinitionDraftFrom,
  agentDefinitionMutationFromDraft,
  validateAgentDefinitionDraft,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/agentDefinitionFormModel.js');
const editorSource = readFileSync(
  new URL('../src/features/settings/AgentDefinitionEditorDialog.tsx', import.meta.url),
  'utf8',
);
const providerQaSource = readFileSync(
  new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url),
  'utf8',
);
const agentManagementSource = readFileSync(
  new URL('../src/features/settings/useAgentDefinitionManagement.ts', import.meta.url),
  'utf8',
);
const managementDialogsSource = readFileSync(
  new URL('../src/features/settings/SettingsManagementDialogs.tsx', import.meta.url),
  'utf8',
);

const definition = {
  id: 'agent-reviewer',
  tenant_id: 'tenant-a',
  project_id: 'project-a',
  name: 'release_reviewer',
  display_name: 'Release reviewer',
  system_prompt: 'Review releases with evidence.',
  trigger: {
    description: 'Review release readiness',
    keywords: ['release', 'readiness'],
    examples: ['Review this candidate'],
  },
  model: 'openai/gpt-5.1',
  temperature: 0.3,
  max_tokens: 6000,
  max_iterations: 18,
  allowed_tools: ['read', 'git_diff'],
  allowed_skills: ['code-verification'],
  allowed_mcp_servers: ['github'],
  can_spawn: true,
  max_spawn_depth: 2,
  agent_to_agent_enabled: true,
  agent_to_agent_allowlist: ['agent-planner'],
  discoverable: false,
  max_retries: 2,
  fallback_models: ['anthropic/claude-sonnet-4-5'],
  spawn_policy: {
    max_depth: 2,
    max_active_runs: 4,
    max_children_per_requester: 2,
    allowed_subagents: ['agent-planner', 'agent-researcher'],
  },
  tool_policy: {
    allow: ['read', 'git_diff'],
    deny: ['terminal'],
    precedence: 'allow_first',
  },
  session_policy: {
    dm_scope: 'per_chat',
    max_messages: 200,
    idle_reset_minutes: 30,
    daily_reset_hour: 4,
    session_ttl_hours: 72,
  },
  delegate_config: {
    capability_tier: 'read_write',
    max_delegation_depth: 2,
    allowed_tools: ['read', 'git_diff'],
    budget_limit_tokens: 12000,
  },
  execution_backend: {
    type: 'acp_external',
    acp_agent_key: 'review-agent',
  },
  workspace_config: {
    sandbox_scope: 'agent',
    base_path: '/srv/agents/reviewer',
  },
};

test('new Agent definition drafts inherit the selected project and safe runtime defaults', () => {
  assert.deepEqual(agentDefinitionDraftFrom(null, 'project-a'), {
    name: '',
    displayName: '',
    systemPrompt: '',
    scopeId: 'project-a',
    triggerDescription: 'Default agent trigger',
    triggerKeywords: '',
    triggerExamples: '',
    model: 'inherit',
    executionBackendType: 'memstack',
    executionBackendAcpAgentKey: '',
    workspaceType: 'shared',
    workspaceBaseDir: '',
    temperature: 0.7,
    maxTokens: 4096,
    maxIterations: 10,
    allowedTools: '*',
    allowedSkills: '',
    allowedMcpServers: '',
    fallbackModels: '',
    canSpawn: false,
    maxSpawnDepth: 3,
    spawnMaxActiveRuns: null,
    spawnMaxChildrenPerRequester: null,
    spawnAllowedSubagents: '',
    agentToAgentEnabled: false,
    agentToAgentAllowlist: '',
    discoverable: true,
    maxRetries: 0,
    toolPolicyPrecedence: 'deny_first',
    toolPolicyAllow: '',
    toolPolicyDeny: '',
    sessionPolicyDmScope: '',
    sessionPolicyMaxMessages: null,
    sessionPolicyIdleResetMinutes: null,
    sessionPolicyDailyResetHour: null,
    sessionPolicyTtlHours: null,
    delegateCapabilityTier: '',
    delegateMaxDelegationDepth: null,
    delegateAllowedTools: '',
    delegateBudgetLimitTokens: null,
    hadSpawnPolicy: false,
    hadToolPolicy: false,
    hadSessionPolicy: false,
    hadDelegateConfig: false,
  });
});

test('editing an Agent definition preserves authoritative identity, runtime, and policy fields', () => {
  assert.deepEqual(agentDefinitionDraftFrom(definition, 'project-other'), {
    name: 'release_reviewer',
    displayName: 'Release reviewer',
    systemPrompt: 'Review releases with evidence.',
    scopeId: 'project-a',
    triggerDescription: 'Review release readiness',
    triggerKeywords: 'release\nreadiness',
    triggerExamples: 'Review this candidate',
    model: 'openai/gpt-5.1',
    executionBackendType: 'acp_external',
    executionBackendAcpAgentKey: 'review-agent',
    workspaceType: 'isolated',
    workspaceBaseDir: '/srv/agents/reviewer',
    temperature: 0.3,
    maxTokens: 6000,
    maxIterations: 18,
    allowedTools: 'read\ngit_diff',
    allowedSkills: 'code-verification',
    allowedMcpServers: 'github',
    fallbackModels: 'anthropic/claude-sonnet-4-5',
    canSpawn: true,
    maxSpawnDepth: 2,
    spawnMaxActiveRuns: 4,
    spawnMaxChildrenPerRequester: 2,
    spawnAllowedSubagents: 'agent-planner\nagent-researcher',
    agentToAgentEnabled: true,
    agentToAgentAllowlist: 'agent-planner',
    discoverable: false,
    maxRetries: 2,
    toolPolicyPrecedence: 'allow_first',
    toolPolicyAllow: 'read\ngit_diff',
    toolPolicyDeny: 'terminal',
    sessionPolicyDmScope: 'per_chat',
    sessionPolicyMaxMessages: 200,
    sessionPolicyIdleResetMinutes: 30,
    sessionPolicyDailyResetHour: 4,
    sessionPolicyTtlHours: 72,
    delegateCapabilityTier: 'read_write',
    delegateMaxDelegationDepth: 2,
    delegateAllowedTools: 'read\ngit_diff',
    delegateBudgetLimitTokens: 12000,
    hadSpawnPolicy: true,
    hadToolPolicy: true,
    hadSessionPolicy: true,
    hadDelegateConfig: true,
  });
});

test('Agent definition mutations normalize list fields and fail closed for empty A2A allowlists', () => {
  const draft = {
    ...agentDefinitionDraftFrom(definition, null),
    scopeId: '',
    allowedTools: 'read, git_diff\nread',
    fallbackModels: ' model-a, model-b ',
    agentToAgentAllowlist: 'agent-planner, agent-reviewer, agent-planner',
    spawnAllowedSubagents: 'agent-planner, agent-researcher, agent-planner',
    toolPolicyAllow: 'read, git_diff, read',
    toolPolicyDeny: 'terminal, terminal',
    delegateAllowedTools: 'read, git_diff, read',
  };

  assert.deepEqual(agentDefinitionMutationFromDraft(draft), {
    name: 'release_reviewer',
    display_name: 'Release reviewer',
    system_prompt: 'Review releases with evidence.',
    project_id: null,
    trigger_description: 'Review release readiness',
    trigger_keywords: ['release', 'readiness'],
    trigger_examples: ['Review this candidate'],
    model: 'openai/gpt-5.1',
    execution_backend: {
      type: 'acp_external',
      acp_agent_key: 'review-agent',
    },
    workspace_config: {
      type: 'isolated',
      base_dir: '/srv/agents/reviewer',
    },
    temperature: 0.3,
    max_tokens: 6000,
    max_iterations: 18,
    allowed_tools: ['read', 'git_diff'],
    allowed_skills: ['code-verification'],
    allowed_mcp_servers: ['github'],
    fallback_models: ['model-a', 'model-b'],
    can_spawn: true,
    max_spawn_depth: 2,
    agent_to_agent_enabled: true,
    agent_to_agent_allowlist: ['agent-planner', 'agent-reviewer'],
    discoverable: false,
    max_retries: 2,
    spawn_policy: {
      max_depth: 2,
      max_active_runs: 4,
      max_children_per_requester: 2,
      allowed_subagents: ['agent-planner', 'agent-researcher'],
    },
    tool_policy: {
      allow: ['read', 'git_diff'],
      deny: ['terminal'],
      precedence: 'allow_first',
    },
    session_policy: {
      dm_scope: 'per_chat',
      max_messages: 200,
      idle_reset_minutes: 30,
      daily_reset_hour: 4,
      session_ttl_hours: 72,
    },
    delegate_config: {
      capability_tier: 'read_write',
      max_delegation_depth: 2,
      allowed_tools: ['read', 'git_diff'],
      budget_limit_tokens: 12000,
    },
  });

  assert.deepEqual(
    agentDefinitionMutationFromDraft({ ...draft, agentToAgentAllowlist: '' })
      .agent_to_agent_allowlist,
    [],
  );

  const clearedPolicies = agentDefinitionMutationFromDraft({
    ...draft,
    canSpawn: false,
    spawnMaxActiveRuns: null,
    spawnMaxChildrenPerRequester: null,
    spawnAllowedSubagents: '',
    toolPolicyPrecedence: 'deny_first',
    toolPolicyAllow: '',
    toolPolicyDeny: '',
    sessionPolicyDmScope: '',
    sessionPolicyMaxMessages: null,
    sessionPolicyIdleResetMinutes: null,
    sessionPolicyDailyResetHour: null,
    sessionPolicyTtlHours: null,
    delegateCapabilityTier: '',
    delegateMaxDelegationDepth: null,
    delegateAllowedTools: '',
    delegateBudgetLimitTokens: null,
  });
  assert.equal(clearedPolicies.spawn_policy, null);
  assert.equal(clearedPolicies.tool_policy, null);
  assert.equal(clearedPolicies.session_policy, null);
  assert.equal(clearedPolicies.delegate_config, null);
});

test('Agent definition validation covers Web naming and backend runtime constraints', () => {
  const valid = agentDefinitionDraftFrom(definition, null);
  assert.deepEqual(validateAgentDefinitionDraft(valid), {});
  assert.deepEqual(
    validateAgentDefinitionDraft({
      ...valid,
      name: 'Release Reviewer',
      executionBackendAcpAgentKey: '',
      displayName: '',
      systemPrompt: '',
      temperature: 2.1,
      maxTokens: 0,
      maxIterations: 0,
      maxSpawnDepth: -1,
      spawnMaxActiveRuns: 0,
      spawnMaxChildrenPerRequester: 0,
      sessionPolicyMaxMessages: 0,
      sessionPolicyIdleResetMinutes: 0,
      sessionPolicyDailyResetHour: 24,
      sessionPolicyTtlHours: 0,
      delegateMaxDelegationDepth: -1,
      delegateBudgetLimitTokens: 0,
      maxRetries: -1,
    }),
    {
      name: 'invalid_name',
      executionBackendAcpAgentKey: 'required',
      displayName: 'required',
      systemPrompt: 'required',
      temperature: 'temperature_range',
      maxTokens: 'positive_integer',
      maxIterations: 'positive_integer',
      maxSpawnDepth: 'non_negative_integer',
      spawnMaxActiveRuns: 'positive_integer',
      spawnMaxChildrenPerRequester: 'positive_integer',
      sessionPolicyMaxMessages: 'positive_integer',
      sessionPolicyIdleResetMinutes: 'positive_integer',
      sessionPolicyDailyResetHour: 'hour_range',
      sessionPolicyTtlHours: 'positive_integer',
      delegateMaxDelegationDepth: 'non_negative_integer',
      delegateBudgetLimitTokens: 'positive_integer',
      maxRetries: 'non_negative_integer',
    },
  );
});

test('Agent definition editor exposes structured spawn and tool policy controls', () => {
  assert.match(editorSource, /draft\.spawnMaxActiveRuns/);
  assert.match(editorSource, /draft\.spawnMaxChildrenPerRequester/);
  assert.match(editorSource, /draft\.spawnAllowedSubagents/);
  assert.match(editorSource, /draft\.toolPolicyPrecedence/);
  assert.match(editorSource, /draft\.toolPolicyAllow/);
  assert.match(editorSource, /draft\.toolPolicyDeny/);
  assert.match(editorSource, /draft\.sessionPolicyDmScope/);
  assert.match(editorSource, /draft\.sessionPolicyMaxMessages/);
  assert.match(editorSource, /draft\.sessionPolicyIdleResetMinutes/);
  assert.match(editorSource, /draft\.sessionPolicyDailyResetHour/);
  assert.match(editorSource, /draft\.sessionPolicyTtlHours/);
  assert.match(editorSource, /draft\.delegateCapabilityTier/);
  assert.match(editorSource, /draft\.delegateMaxDelegationDepth/);
  assert.match(editorSource, /draft\.delegateAllowedTools/);
  assert.match(editorSource, /draft\.delegateBudgetLimitTokens/);
  assert.match(editorSource, /draft\.executionBackendType/);
  assert.match(editorSource, /draft\.executionBackendAcpAgentKey/);
  assert.match(editorSource, /draft\.workspaceType/);
  assert.match(editorSource, /draft\.workspaceBaseDir/);
  assert.match(editorSource, /agent\.enabled \|\|/);
});

test('provider settings QA round-trips structured Agent policies', () => {
  assert.match(providerQaSource, /body\.spawn_policy/);
  assert.match(providerQaSource, /current\?\.spawn_policy/);
  assert.match(providerQaSource, /body\.tool_policy/);
  assert.match(providerQaSource, /current\?\.tool_policy/);
  assert.match(providerQaSource, /body\.session_policy/);
  assert.match(providerQaSource, /current\?\.session_policy/);
  assert.match(providerQaSource, /body\.delegate_config/);
  assert.match(providerQaSource, /current\?\.delegate_config/);
  assert.match(providerQaSource, /body\.execution_backend/);
  assert.match(providerQaSource, /current\?\.execution_backend/);
  assert.match(providerQaSource, /body\.workspace_config/);
  assert.match(providerQaSource, /current\?\.workspace_config/);
  assert.match(providerQaSource, /external-agents/);
  assert.match(agentManagementSource, /listManagedExternalAcpAgents/);
  assert.match(managementDialogsSource, /externalAcpAgents/);
});
