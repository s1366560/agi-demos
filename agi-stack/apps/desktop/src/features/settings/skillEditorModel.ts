import type { ManagedSkill, ManagedSkillCreateMutation, ManagedSkillMutation } from '../../types';

export type SkillEditorDraft = {
  name: string;
  description: string;
  scope: 'tenant' | 'project';
  projectId: string;
  body: string;
  allowedToolsRaw: string;
  metadata: string;
  license: string;
  compatibility: string;
  specVersion: string;
};

export type SkillDraftField = keyof SkillEditorDraft;
export type SkillDraftError = 'required' | 'invalid_name' | 'invalid_metadata' | 'too_long';
export type SkillDraftErrors = Partial<Record<SkillDraftField, SkillDraftError>>;

const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const FRONTMATTER_PATTERN = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

export function skillDraftFrom(
  skill: ManagedSkill | null,
  initialProjectId: string | null
): SkillEditorDraft {
  if (!skill) {
    return {
      name: '',
      description: '',
      scope: initialProjectId ? 'project' : 'tenant',
      projectId: initialProjectId ?? '',
      body: '# new-skill\n\n## Instructions\n\n',
      allowedToolsRaw: '',
      metadata: '{}',
      license: '',
      compatibility: '',
      specVersion: '1.0',
    };
  }

  return {
    name: skill.name,
    description: skill.description,
    scope: skill.scope === 'project' ? 'project' : 'tenant',
    projectId: stringValue(skill.project_id),
    body: extractSkillBody(skill.full_content, skill.name),
    allowedToolsRaw: skill.allowed_tools_raw ?? formatTools(skill.tools),
    metadata: JSON.stringify(skill.metadata ?? {}, null, 2),
    license: skill.license ?? '',
    compatibility: skill.compatibility ?? '',
    specVersion: skill.spec_version ?? '1.0',
  };
}

export function skillCreateMutationFromDraft(draft: SkillEditorDraft): ManagedSkillCreateMutation {
  return {
    ...skillUpdateMutationFromDraft(draft),
    scope: draft.scope,
    project_id: draft.scope === 'project' ? (compact(draft.projectId) ?? null) : null,
  };
}

export function skillUpdateMutationFromDraft(draft: SkillEditorDraft): ManagedSkillMutation {
  const metadata = parseMetadata(draft.metadata);
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    tools: parseAllowedTools(draft.allowedToolsRaw),
    full_content: buildSkillContent(draft, metadata),
    metadata,
    license: compact(draft.license) ?? null,
    compatibility: compact(draft.compatibility) ?? null,
    allowed_tools_raw: compact(draft.allowedToolsRaw) ?? null,
    spec_version: compact(draft.specVersion) ?? '1.0',
  };
}

export function validateSkillDraft(draft: SkillEditorDraft): SkillDraftErrors {
  const errors: SkillDraftErrors = {};
  const name = draft.name.trim();
  if (!name) errors.name = 'required';
  else if (!SKILL_NAME_PATTERN.test(name)) errors.name = 'invalid_name';
  if (!draft.description.trim()) errors.description = 'required';
  else if (draft.description.trim().length > 1024) errors.description = 'too_long';
  if (draft.scope === 'project' && !draft.projectId.trim()) errors.projectId = 'required';
  if (draft.license.trim().length > 200) errors.license = 'too_long';
  if (draft.compatibility.trim().length > 500) errors.compatibility = 'too_long';
  if (draft.allowedToolsRaw.trim().length > 2000) errors.allowedToolsRaw = 'too_long';
  if (draft.specVersion.trim().length > 32) errors.specVersion = 'too_long';
  try {
    parseMetadata(draft.metadata);
  } catch {
    errors.metadata = 'invalid_metadata';
  }
  return errors;
}

function buildSkillContent(draft: SkillEditorDraft, metadata: Record<string, unknown>): string {
  const lines = [
    '---',
    `name: ${draft.name.trim()}`,
    `description: ${JSON.stringify(draft.description.trim())}`,
  ];
  const license = compact(draft.license);
  const compatibility = compact(draft.compatibility);
  const allowedTools = compact(draft.allowedToolsRaw);
  if (license) lines.push(`license: ${JSON.stringify(license)}`);
  if (compatibility) lines.push(`compatibility: ${JSON.stringify(compatibility)}`);
  if (allowedTools) lines.push(`allowed-tools: ${JSON.stringify(allowedTools)}`);
  if (Object.keys(metadata).length > 0) lines.push(`metadata: ${JSON.stringify(metadata)}`);
  lines.push('---');
  const body = compact(draft.body) ?? `# ${draft.name.trim()}\n\n${draft.description.trim()}`;
  return `${lines.join('\n')}\n\n${body}\n`;
}

function extractSkillBody(content: string | null | undefined, fallbackName: string): string {
  const body = content?.replace(FRONTMATTER_PATTERN, '').trim();
  return body || `# ${fallbackName || 'skill'}\n\n## Instructions\n\n`;
}

function parseAllowedTools(value: string): string[] {
  const seen = new Set<string>();
  const tools = value
    .trim()
    .split(/\s+/)
    .filter((item) => Boolean(item) && !seen.has(item) && Boolean(seen.add(item)));
  return tools.length > 0 ? tools : ['*'];
}

function formatTools(tools: string[]): string {
  return tools.length === 1 && tools[0] === '*' ? '' : tools.join(' ');
}

function parseMetadata(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed: unknown = JSON.parse(trimmed);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Skill metadata must be an object');
  }
  return parsed as Record<string, unknown>;
}

function compact(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
