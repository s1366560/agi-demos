/** Parse the portable metadata object without silently converting nonfinite numbers to null. */
export function parseMemoryMetadata(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text, (_key, item: unknown) => {
      if (typeof item === 'number' && !Number.isFinite(item)) throw new Error('nonfinite');
      return item;
    });
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
    if (new TextEncoder().encode(JSON.stringify(value)).length > 65_536) return null;
    return value as Record<string, unknown>;
  } catch {
    return null;
  }
}
