type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export function canonicalJsonV2(value: unknown): string {
  return serialize(value, new Set<object>());
}

export async function digestV2(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJsonV2(value));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

const digestByIdentity = new WeakMap<object, Promise<string>>();

/** Reuse a digest when the same immutable object is checked more than once. */
export function digestCachedV2(value: object): Promise<string> {
  const cached = digestByIdentity.get(value);
  if (cached !== undefined) return cached;
  const pending = digestV2(value);
  digestByIdentity.set(value, pending);
  return pending;
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
