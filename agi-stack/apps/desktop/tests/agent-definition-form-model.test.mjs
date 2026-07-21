import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  agentDefinitionDraftFrom,
  agentDefinitionMutationFromDraft,
  validateAgentDefinitionDraft,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/agentDefinitionFormModel.js');

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
    temperature: 0.7,
    maxTokens: 4096,
    maxIterations: 10,
    allowedTools: '*',
    allowedSkills: '',
    allowedMcpServers: '',
    fallbackModels: '',
    canSpawn: false,
    maxSpawnDepth: 3,
    agentToAgentEnabled: false,
    agentToAgentAllowlist: '',
    discoverable: true,
    maxRetries: 0,
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
    temperature: 0.3,
    maxTokens: 6000,
    maxIterations: 18,
    allowedTools: 'read\ngit_diff',
    allowedSkills: 'code-verification',
    allowedMcpServers: 'github',
    fallbackModels: 'anthropic/claude-sonnet-4-5',
    canSpawn: true,
    maxSpawnDepth: 2,
    agentToAgentEnabled: true,
    agentToAgentAllowlist: 'agent-planner',
    discoverable: false,
    maxRetries: 2,
  });
});

test('Agent definition mutations normalize list fields and fail closed for empty A2A allowlists', () => {
  const draft = {
    ...agentDefinitionDraftFrom(definition, null),
    scopeId: '',
    allowedTools: 'read, git_diff\nread',
    fallbackModels: ' model-a, model-b ',
    agentToAgentAllowlist: 'agent-planner, agent-reviewer, agent-planner',
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
  });

  assert.deepEqual(
    agentDefinitionMutationFromDraft({ ...draft, agentToAgentAllowlist: '' })
      .agent_to_agent_allowlist,
    [],
  );
});

test('Agent definition validation covers Web naming and backend runtime constraints', () => {
  const valid = agentDefinitionDraftFrom(definition, null);
  assert.deepEqual(validateAgentDefinitionDraft(valid), {});
  assert.deepEqual(
    validateAgentDefinitionDraft({
      ...valid,
      name: 'Release Reviewer',
      displayName: '',
      systemPrompt: '',
      temperature: 2.1,
      maxTokens: 0,
      maxIterations: 0,
      maxSpawnDepth: -1,
      maxRetries: -1,
    }),
    {
      name: 'invalid_name',
      displayName: 'required',
      systemPrompt: 'required',
      temperature: 'temperature_range',
      maxTokens: 'positive_integer',
      maxIterations: 'positive_integer',
      maxSpawnDepth: 'non_negative_integer',
      maxRetries: 'non_negative_integer',
    },
  );
});
