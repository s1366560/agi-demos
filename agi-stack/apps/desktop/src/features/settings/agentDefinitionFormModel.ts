import type { ManagedAgentDefinition, ManagedAgentDefinitionMutation } from '../../types';

export type AgentDefinitionEditorDraft = {
  name: string;
  displayName: string;
  systemPrompt: string;
  scopeId: string;
  triggerDescription: string;
  triggerKeywords: string;
  triggerExamples: string;
  model: string;
  temperature: number;
  maxTokens: number;
  maxIterations: number;
  allowedTools: string;
  allowedSkills: string;
  allowedMcpServers: string;
  fallbackModels: string;
  canSpawn: boolean;
  maxSpawnDepth: number;
  agentToAgentEnabled: boolean;
  agentToAgentAllowlist: string;
  discoverable: boolean;
  maxRetries: number;
};

export type AgentDefinitionDraftField = keyof AgentDefinitionEditorDraft;
export type AgentDefinitionDraftError =
  | 'required'
  | 'invalid_name'
  | 'temperature_range'
  | 'positive_integer'
  | 'non_negative_integer';

export type AgentDefinitionDraftErrors = Partial<
  Record<AgentDefinitionDraftField, AgentDefinitionDraftError>
>;

const AGENT_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

export function agentDefinitionDraftFrom(
  definition: ManagedAgentDefinition | null,
  initialProjectId: string | null,
): AgentDefinitionEditorDraft {
  if (!definition) {
    return {
      name: '',
      displayName: '',
      systemPrompt: '',
      scopeId: initialProjectId ?? '',
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
    };
  }

  const trigger = recordValue(definition.trigger);
  return {
    name: definition.name,
    displayName: definition.display_name ?? '',
    systemPrompt: definition.system_prompt ?? '',
    scopeId: stringValue(definition.project_id),
    triggerDescription: stringValue(trigger?.description) || 'Default agent trigger',
    triggerKeywords: stringList(trigger?.keywords).join('\n'),
    triggerExamples: stringList(trigger?.examples).join('\n'),
    model: stringValue(definition.model) || definition.model_name || 'inherit',
    temperature: numberValue(definition.temperature, 0.7),
    maxTokens: numberValue(definition.max_tokens, 4096),
    maxIterations: numberValue(definition.max_iterations, 10),
    allowedTools: stringList(definition.allowed_tools).join('\n'),
    allowedSkills: stringList(definition.allowed_skills).join('\n'),
    allowedMcpServers: stringList(definition.allowed_mcp_servers).join('\n'),
    fallbackModels: stringList(definition.fallback_models).join('\n'),
    canSpawn: booleanValue(definition.can_spawn, false),
    maxSpawnDepth: numberValue(definition.max_spawn_depth, 3),
    agentToAgentEnabled: booleanValue(definition.agent_to_agent_enabled, false),
    agentToAgentAllowlist: stringList(definition.agent_to_agent_allowlist).join('\n'),
    discoverable: booleanValue(definition.discoverable, true),
    maxRetries: numberValue(definition.max_retries, 0),
  };
}

export function agentDefinitionMutationFromDraft(
  draft: AgentDefinitionEditorDraft,
): ManagedAgentDefinitionMutation {
  return {
    name: draft.name.trim(),
    display_name: draft.displayName.trim(),
    system_prompt: draft.systemPrompt.trim(),
    project_id: draft.scopeId.trim() || null,
    trigger_description: draft.triggerDescription.trim() || 'Default agent trigger',
    trigger_keywords: normalizedList(draft.triggerKeywords),
    trigger_examples: normalizedList(draft.triggerExamples),
    model: draft.model.trim() || 'inherit',
    temperature: draft.temperature,
    max_tokens: draft.maxTokens,
    max_iterations: draft.maxIterations,
    allowed_tools: normalizedList(draft.allowedTools),
    allowed_skills: normalizedList(draft.allowedSkills),
    allowed_mcp_servers: normalizedList(draft.allowedMcpServers),
    fallback_models: normalizedList(draft.fallbackModels),
    can_spawn: draft.canSpawn,
    max_spawn_depth: draft.maxSpawnDepth,
    agent_to_agent_enabled: draft.agentToAgentEnabled,
    agent_to_agent_allowlist: draft.agentToAgentEnabled
      ? normalizedList(draft.agentToAgentAllowlist)
      : null,
    discoverable: draft.discoverable,
    max_retries: draft.maxRetries,
  };
}

export function validateAgentDefinitionDraft(
  draft: AgentDefinitionEditorDraft,
): AgentDefinitionDraftErrors {
  const errors: AgentDefinitionDraftErrors = {};
  const name = draft.name.trim();
  if (!name) errors.name = 'required';
  else if (!AGENT_NAME_PATTERN.test(name)) errors.name = 'invalid_name';
  if (!draft.displayName.trim()) errors.displayName = 'required';
  if (!draft.systemPrompt.trim()) errors.systemPrompt = 'required';
  if (!draft.triggerDescription.trim()) errors.triggerDescription = 'required';
  if (!Number.isFinite(draft.temperature) || draft.temperature < 0 || draft.temperature > 2) {
    errors.temperature = 'temperature_range';
  }
  if (!isPositiveInteger(draft.maxTokens)) errors.maxTokens = 'positive_integer';
  if (!isPositiveInteger(draft.maxIterations)) errors.maxIterations = 'positive_integer';
  if (!isNonNegativeInteger(draft.maxSpawnDepth)) {
    errors.maxSpawnDepth = 'non_negative_integer';
  }
  if (!isNonNegativeInteger(draft.maxRetries)) errors.maxRetries = 'non_negative_integer';
  return errors;
}

function normalizedList(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => Boolean(item) && !seen.has(item) && Boolean(seen.add(item)));
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').map((item) => item.trim())
    : [];
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

function isNonNegativeInteger(value: number): boolean {
  return Number.isInteger(value) && value >= 0;
}
