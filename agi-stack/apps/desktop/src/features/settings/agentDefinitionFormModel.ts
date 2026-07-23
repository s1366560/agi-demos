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
  spawnMaxActiveRuns: number | null;
  spawnMaxChildrenPerRequester: number | null;
  spawnAllowedSubagents: string;
  agentToAgentEnabled: boolean;
  agentToAgentAllowlist: string;
  discoverable: boolean;
  maxRetries: number;
  toolPolicyPrecedence: 'allow_first' | 'deny_first';
  toolPolicyAllow: string;
  toolPolicyDeny: string;
  hadSpawnPolicy: boolean;
  hadToolPolicy: boolean;
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
      hadSpawnPolicy: false,
      hadToolPolicy: false,
    };
  }

  const trigger = recordValue(definition.trigger);
  const spawnPolicy = recordValue(definition.spawn_policy);
  const toolPolicy = recordValue(definition.tool_policy);
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
    maxSpawnDepth: numberValue(spawnPolicy?.max_depth, numberValue(definition.max_spawn_depth, 3)),
    spawnMaxActiveRuns: optionalNumberValue(spawnPolicy?.max_active_runs),
    spawnMaxChildrenPerRequester: optionalNumberValue(
      spawnPolicy?.max_children_per_requester,
    ),
    spawnAllowedSubagents: stringList(spawnPolicy?.allowed_subagents).join('\n'),
    agentToAgentEnabled: booleanValue(definition.agent_to_agent_enabled, false),
    agentToAgentAllowlist: stringList(definition.agent_to_agent_allowlist).join('\n'),
    discoverable: booleanValue(definition.discoverable, true),
    maxRetries: numberValue(definition.max_retries, 0),
    toolPolicyPrecedence:
      toolPolicy?.precedence === 'allow_first' ? 'allow_first' : 'deny_first',
    toolPolicyAllow: stringList(toolPolicy?.allow).join('\n'),
    toolPolicyDeny: stringList(toolPolicy?.deny).join('\n'),
    hadSpawnPolicy: spawnPolicy !== null,
    hadToolPolicy: toolPolicy !== null,
  };
}

export function agentDefinitionMutationFromDraft(
  draft: AgentDefinitionEditorDraft,
): ManagedAgentDefinitionMutation {
  const spawnAllowedSubagents = normalizedList(draft.spawnAllowedSubagents);
  const hasSpawnPolicyFields =
    draft.canSpawn ||
    draft.spawnMaxActiveRuns !== null ||
    draft.spawnMaxChildrenPerRequester !== null ||
    spawnAllowedSubagents.length > 0;
  const spawnPolicy = hasSpawnPolicyFields
    ? {
        max_depth: draft.maxSpawnDepth,
        max_active_runs: draft.spawnMaxActiveRuns ?? 16,
        max_children_per_requester: draft.spawnMaxChildrenPerRequester ?? 8,
        allowed_subagents: spawnAllowedSubagents.length > 0 ? spawnAllowedSubagents : null,
      }
    : draft.hadSpawnPolicy
      ? null
      : undefined;
  const toolPolicyAllow = normalizedList(draft.toolPolicyAllow);
  const toolPolicyDeny = normalizedList(draft.toolPolicyDeny);
  const hasToolPolicyFields =
    toolPolicyAllow.length > 0 ||
    toolPolicyDeny.length > 0 ||
    draft.toolPolicyPrecedence !== 'deny_first';
  const toolPolicy = hasToolPolicyFields
    ? {
        allow: toolPolicyAllow,
        deny: toolPolicyDeny,
        precedence: draft.toolPolicyPrecedence,
      }
    : draft.hadToolPolicy
      ? null
      : undefined;
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
    ...(spawnPolicy !== undefined ? { spawn_policy: spawnPolicy } : {}),
    ...(toolPolicy !== undefined ? { tool_policy: toolPolicy } : {}),
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
  if (
    draft.spawnMaxActiveRuns !== null &&
    !isPositiveInteger(draft.spawnMaxActiveRuns)
  ) {
    errors.spawnMaxActiveRuns = 'positive_integer';
  }
  if (
    draft.spawnMaxChildrenPerRequester !== null &&
    !isPositiveInteger(draft.spawnMaxChildrenPerRequester)
  ) {
    errors.spawnMaxChildrenPerRequester = 'positive_integer';
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

function optionalNumberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
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
