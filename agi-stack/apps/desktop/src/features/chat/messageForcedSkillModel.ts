export type StructuredMessageMetadata = {
  metadata?: unknown;
};

export function forcedSkillNameFromMessage(value: StructuredMessageMetadata): string | null {
  if (!isRecord(value.metadata)) return null;
  for (const key of ['forcedSkillName', 'forced_skill_name']) {
    const candidate = value.metadata[key];
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
