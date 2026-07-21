import type { ManagedSubAgent, ManagedSubAgentMutation } from '../../types';

export type SubAgentEditorDraft = {
  name: string;
  displayName: string;
  systemPrompt: string;
  scopeId: string;
  triggerDescription: string;
  triggerKeywords: string;
  triggerExamples: string;
  model: string;
  color: string;
  temperature: number;
  maxTokens: number;
  maxIterations: number;
  allowedTools: string;
  allowedSkills: string;
  allowedMcpServers: string;
};

export type SubAgentDraftField = keyof SubAgentEditorDraft;
export type SubAgentDraftError =
  | 'required'
  | 'invalid_name'
  | 'temperature_range'
  | 'positive_integer';
export type SubAgentDraftErrors = Partial<Record<SubAgentDraftField, SubAgentDraftError>>;

const SUBAGENT_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

export function subAgentDraftFrom(
  subagent: ManagedSubAgent | null,
  initialProjectId: string | null,
): SubAgentEditorDraft {
  if (!subagent) {
    return {
      name: '',
      displayName: '',
      systemPrompt: '',
      scopeId: initialProjectId ?? '',
      triggerDescription: '',
      triggerKeywords: '',
      triggerExamples: '',
      model: 'inherit',
      color: 'blue',
      temperature: 0.7,
      maxTokens: 4096,
      maxIterations: 10,
      allowedTools: '*',
      allowedSkills: '',
      allowedMcpServers: '',
    };
  }

  const trigger = recordValue(subagent.trigger);
  return {
    name: subagent.name,
    displayName: subagent.display_name ?? '',
    systemPrompt: subagent.system_prompt ?? '',
    scopeId: stringValue(subagent.project_id),
    triggerDescription: stringValue(trigger?.description),
    triggerKeywords: stringList(trigger?.keywords).join('\n'),
    triggerExamples: stringList(trigger?.examples).join('\n'),
    model: subagent.model ?? 'inherit',
    color: subagent.color ?? 'blue',
    temperature: numberValue(subagent.temperature, 0.7),
    maxTokens: numberValue(subagent.max_tokens, 4096),
    maxIterations: numberValue(subagent.max_iterations, 10),
    allowedTools: stringList(subagent.allowed_tools).join('\n'),
    allowedSkills: stringList(subagent.allowed_skills).join('\n'),
    allowedMcpServers: stringList(subagent.allowed_mcp_servers).join('\n'),
  };
}

export function subAgentMutationFromDraft(
  draft: SubAgentEditorDraft,
): ManagedSubAgentMutation {
  return {
    name: draft.name.trim(),
    display_name: draft.displayName.trim(),
    system_prompt: draft.systemPrompt.trim(),
    project_id: draft.scopeId.trim() || null,
    trigger_description: draft.triggerDescription.trim(),
    trigger_keywords: normalizedList(draft.triggerKeywords),
    trigger_examples: normalizedList(draft.triggerExamples),
    model: draft.model.trim() || 'inherit',
    color: draft.color.trim() || 'blue',
    temperature: draft.temperature,
    max_tokens: draft.maxTokens,
    max_iterations: draft.maxIterations,
    allowed_tools: normalizedList(draft.allowedTools),
    allowed_skills: normalizedList(draft.allowedSkills),
    allowed_mcp_servers: normalizedList(draft.allowedMcpServers),
    metadata: null,
  };
}

export function validateSubAgentDraft(draft: SubAgentEditorDraft): SubAgentDraftErrors {
  const errors: SubAgentDraftErrors = {};
  const name = draft.name.trim();
  if (!name) errors.name = 'required';
  else if (!SUBAGENT_NAME_PATTERN.test(name)) errors.name = 'invalid_name';
  if (!draft.displayName.trim()) errors.displayName = 'required';
  if (!draft.systemPrompt.trim()) errors.systemPrompt = 'required';
  if (!draft.triggerDescription.trim()) errors.triggerDescription = 'required';
  if (!Number.isFinite(draft.temperature) || draft.temperature < 0 || draft.temperature > 2) {
    errors.temperature = 'temperature_range';
  }
  if (!isPositiveInteger(draft.maxTokens)) errors.maxTokens = 'positive_integer';
  if (!isPositiveInteger(draft.maxIterations)) errors.maxIterations = 'positive_integer';
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

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}
