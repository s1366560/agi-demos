import type { SkillResponse } from '@/types/agent';

export const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const FRONTMATTER_RE = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

export interface SkillPackageFormValues {
  name: string;
  description: string;
  project_id?: string;
  body?: string;
  metadata?: string;
  license?: string;
  compatibility?: string;
  allowed_tools_raw?: string;
  spec_version?: string;
}

export function compact(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function parseMetadata(value: string | undefined): Record<string, unknown> | undefined {
  const trimmed = value?.trim();
  if (!trimmed) {
    return undefined;
  }
  return JSON.parse(trimmed) as Record<string, unknown>;
}

export function formatMetadata(metadata: Record<string, unknown> | undefined): string {
  return JSON.stringify(metadata ?? {}, null, 2);
}

export function extractSkillBody(content: string | null | undefined, fallbackName: string): string {
  const body = content?.replace(FRONTMATTER_RE, '').trim();
  if (body) {
    return body;
  }
  return `# ${fallbackName || 'skill'}\n\n## Instructions\n\n`;
}

function yamlScalar(value: string): string {
  return JSON.stringify(value);
}

function yamlMetadata(metadata: Record<string, unknown> | undefined): string {
  if (!metadata || Object.keys(metadata).length === 0) {
    return '';
  }

  return `metadata: ${JSON.stringify(metadata)}`;
}

export function buildSkillContent(values: SkillPackageFormValues): string {
  const metadata = parseMetadata(values.metadata);
  const frontmatter = [
    '---',
    `name: ${values.name}`,
    `description: ${yamlScalar(values.description)}`,
  ];
  const license = compact(values.license);
  const compatibility = compact(values.compatibility);
  const allowedTools = compact(values.allowed_tools_raw);
  const metadataBlock = yamlMetadata(metadata);

  if (license) {
    frontmatter.push(`license: ${yamlScalar(license)}`);
  }
  if (compatibility) {
    frontmatter.push(`compatibility: ${yamlScalar(compatibility)}`);
  }
  if (allowedTools) {
    frontmatter.push(`allowed-tools: ${yamlScalar(allowedTools)}`);
  }
  if (metadataBlock) {
    frontmatter.push(metadataBlock);
  }
  frontmatter.push('---');

  return `${frontmatter.join('\n')}\n\n${compact(values.body) ?? `# ${values.name}\n\n${values.description}`}\n`;
}

export function parseAllowedTools(value: string | undefined): string[] {
  const trimmed = value?.trim();
  if (!trimmed) {
    return ['*'];
  }
  return trimmed.split(/\s+/).filter(Boolean);
}

export function formatAllowedToolsForEdit(skill: SkillResponse): string {
  if (skill.allowed_tools_raw) {
    return skill.allowed_tools_raw;
  }
  if (skill.tools.length === 1 && skill.tools[0] === '*') {
    return '';
  }
  return skill.tools.join(' ');
}
