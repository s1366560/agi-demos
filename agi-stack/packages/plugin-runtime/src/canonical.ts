type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export function canonicalJsonV2(value: unknown): string {
  return serialize(value, new Set<object>());
}

export async function digestV2(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJsonV2(value));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function serialize(value: unknown, ancestors: Set<object>): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new TypeError('canonical JSON does not support non-finite numbers');
    }
    return JSON.stringify(value);
  }
  if (typeof value !== 'object') {
    throw new TypeError(`canonical JSON does not support ${typeof value}`);
  }
  if (ancestors.has(value)) {
    throw new TypeError('canonical JSON does not support cyclic values');
  }
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return `[${value.map((item) => serialize(item, ancestors)).join(',')}]`;
    }
    const object = value as Record<string, unknown>;
    const entries = Object.keys(object)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${serialize(object[key], ancestors)}`);
    return `{${entries.join(',')}}`;
  } finally {
    ancestors.delete(value);
  }
}

export type { JsonValue };
