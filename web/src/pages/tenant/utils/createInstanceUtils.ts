export const parseInstanceJsonObject = (
  value: unknown
): Record<string, unknown> | undefined => {
  if (!value) return undefined;
  if (typeof value === 'string') {
    let parsed: unknown;
    try {
      parsed = JSON.parse(value);
    } catch {
      throw new Error('Expected a JSON object');
    }
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    throw new Error('Expected a JSON object');
  }
  if (typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  throw new Error('Expected a JSON object');
};
